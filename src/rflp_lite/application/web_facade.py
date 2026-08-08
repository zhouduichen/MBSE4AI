from __future__ import annotations

import json
from pathlib import Path

from rflp_lite.adapters.sqlite_repository import SQLiteRepository
from rflp_lite.adapters.test_execution_config import ResourceLimits
from rflp_lite.application.demo import run_demo
from rflp_lite.application.project_bridge import (
    analyze_project_state,
    approve_workbench_baseline,
    execute_tests_state,
    verify_contracts_state,
)
from rflp_lite.adapters.test_executor import DEFAULT_TEST_TIMEOUT
from rflp_lite.application.run_catalog import RunRecord, list_runs, load_run
from rflp_lite.application.requirements_workbench import (
    STAKEHOLDER_CATEGORIES,
    accept_traceable,
    confirm_requirements,
    add_stakeholder,
    add_llm_suggestions,
    analyze_artifact,
    generate_draft_model,
    generate_model,
    empty_workbench,
    merge_artifact,
    normalize_stakeholder_category,
    review_item,
    stakeholder_category_label,
    stakeholder_bundle,
)
from rflp_lite.application.requirements_flow import run_requirements_flow
from rflp_lite.application.jobs import JobService
from rflp_lite.application.llm_profiles import LLMProfileService
from rflp_lite.application.interchange import export_rflp, import_rflp
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.application.profile_packs import (
    export_run_record,
    load_profile,
    save_profile,
)
from rflp_lite.application.plugins import invoke_plugin, list_plugins
from rflp_lite.application.sysml_v2 import export_sysml_v2_text, import_sysml_v2_text
from rflp_lite.adapters.mlflow_tracking import track_run_with_mlflow
from rflp_lite.application.scenarios import (
    add_scenario,
    delete_scenario,
    generate_scenario_drafts,
)
from rflp_lite.application.scenario_execution import append_scenario_run, execute_scenario
from rflp_lite.application.workspaces import (
    WorkspaceRef,
    create_managed_workspace,
    list_managed_workspaces,
    managed_workspace,
)
from rflp_lite.domain.errors import ContractViolation, InvariantViolation
from rflp_lite.governance.profile import Profile


class WebFacade:
    def __init__(self, workspace_root: Path, fixture_root: Path | None = None):
        self.workspace_root = workspace_root.resolve()
        self.fixture_root = fixture_root
        self.llm = LLMProfileService()

    def workspaces(self) -> tuple[WorkspaceRef, ...]:
        return list_managed_workspaces(self.workspace_root)

    def workspace(self, name: str) -> WorkspaceRef:
        path = managed_workspace(self.workspace_root, name)
        profile_path = path / "profile.json"
        if not profile_path.is_file():
            raise ContractViolation(f"workspace not found: {name}")
        return WorkspaceRef(name, path, profile_path, True)

    def create_workspace(self, name: str) -> WorkspaceRef:
        return create_managed_workspace(self.workspace_root, name)

    def runs(self, workspace_name: str) -> tuple[RunRecord, ...]:
        return list_runs(self.workspace(workspace_name).path)

    def run(self, workspace_name: str, result_hash: str) -> RunRecord:
        return load_run(self.workspace(workspace_name).path, result_hash)

    def export_run(self, workspace_name: str, result_hash: str) -> dict[str, object]:
        return export_run_record(self.run(workspace_name, result_hash))

    def profile(self, workspace_name: str) -> dict[str, object]:
        return load_profile(self.workspace(workspace_name).path)

    def save_profile(
        self, workspace_name: str, payload: object
    ) -> dict[str, object]:
        workspace = self.workspace(workspace_name)
        normalized = save_profile(workspace.path, payload)
        repository = SQLiteRepository(workspace.path / ".rflp" / "model.db")
        try:
            with repository.transaction():
                repository.record_audit("profile.saved", normalized)
        finally:
            repository.close()
        return normalized

    def export_requirements_rflp(self, workspace_name: str) -> dict[str, object]:
        state = self.requirements(workspace_name)
        if not state or not state.get("rflp"):
            raise ContractViolation("RFLP model not generated")
        return export_rflp(state["rflp"])

    def export_requirements_sysml_v2(self, workspace_name: str) -> str:
        state = self.requirements(workspace_name)
        if not state or not state.get("rflp"):
            raise ContractViolation("RFLP model not generated")
        return export_sysml_v2_text(state["rflp"])

    def import_requirements_rflp(
        self, workspace_name: str, payload: object
    ) -> dict[str, object]:
        state = self.requirements(workspace_name)
        if state is None:
            raise ContractViolation("requirements workbench is empty")
        result = json.loads(canonical_json(state))
        result["rflp"] = import_rflp(payload)
        return self._save_requirements(workspace_name, result, "rflp.imported")

    def import_requirements_sysml_v2(
        self, workspace_name: str, text: str
    ) -> dict[str, object]:
        state = self.requirements(workspace_name)
        if state is None:
            raise ContractViolation("requirements workbench is empty")
        result = json.loads(canonical_json(state))
        result["rflp"] = import_sysml_v2_text(text)
        return self._save_requirements(workspace_name, result, "rflp.sysml_v2_imported")

    def track_run_with_mlflow(
        self,
        workspace_name: str,
        result_hash: str,
        *,
        tracking_uri: str | None = None,
        experiment_name: str = "rflp-lite",
    ) -> dict[str, object]:
        return track_run_with_mlflow(
            self.run(workspace_name, result_hash),
            tracking_uri=tracking_uri,
            experiment_name=experiment_name,
        )

    def plugins(self) -> tuple[dict[str, object], ...]:
        return list_plugins()

    def llm_snapshot(self) -> dict[str, object]:
        return self.llm.snapshot()

    def llm_presets(self) -> dict[str, dict[str, object]]:
        return self.llm.presets()

    def save_llm_profile(self, payload: object) -> dict[str, object]:
        return self.llm.save(payload)

    def test_llm_profile(self, payload: object) -> dict[str, object]:
        return self.llm.test(payload)

    def activate_llm_profile(self, profile_id: str) -> dict[str, object]:
        return self.llm.activate(profile_id)

    def delete_llm_profile(self, profile_id: str) -> None:
        self.llm.delete(profile_id)

    def invoke_plugin(
        self, name: str, payload: dict[str, object]
    ) -> dict[str, object]:
        return invoke_plugin(name, payload)

    def audit(self, workspace_name: str) -> tuple[dict[str, object], ...]:
        workspace = self.workspace(workspace_name)
        database = workspace.path / ".rflp" / "model.db"
        if not database.is_file():
            return ()
        repository = SQLiteRepository(database)
        try:
            return repository.audit_events()
        finally:
            repository.close()

    def execute(self, workspace_name: str, solver: str, seed: int) -> RunRecord:
        workspace = self.workspace(workspace_name)
        profile = Profile(
            solver=solver,
            seed=seed,
            candidate_limit=3,
            timeout_seconds=5,
        )
        result = run_demo(workspace.path, profile, fixture_root=self.fixture_root)
        return load_run(workspace.path, result.result_hash)

    def requirements(self, workspace_name: str) -> dict[str, object] | None:
        workspace = self.workspace(workspace_name)
        repository = SQLiteRepository(workspace.path / ".rflp" / "model.db")
        try:
            state = repository.load_workbench()
            if state is not None:
                state.setdefault("scenarios", [])
                state.setdefault("scenario_runs", [])
                state.setdefault("flow", None)
                for stakeholder in state.get("stakeholders", ()):
                    category = normalize_stakeholder_category(
                        str(stakeholder.get("category", "")),
                        str(stakeholder.get("name", "")),
                    )
                    stakeholder["category"] = category
                    stakeholder["category_label"] = stakeholder_category_label(category)
                if state.get("spans") and not state.get("rflp"):
                    try:
                        state = generate_draft_model(state)
                    except InvariantViolation:
                        # A partially rejected legacy workbench may not have
                        # enough provenance for even a draft; keep it viewable.
                        pass
            return state
        finally:
            repository.close()

    def requirements_guide(self, workspace_name: str) -> dict[str, object]:
        """Return one actionable next step for the guided requirements path."""
        state = self.requirements(workspace_name)
        root = f"/w/{workspace_name}/requirements"
        if state is None:
            return {
                "key": "input",
                "stage": "第 1 步 / 4",
                "title": "先说清楚你想做什么",
                "body": "用一句自然语言描述系统、目标或问题，不要求先写成标准 Requirement。",
                "action_label": "输入需求",
                "action_url": f"{root}/input",
                "steps": (("输入需求", "current"), ("确认理解", "waiting"), ("生成正式 RFLP", "waiting"), ("项目验证", "optional")),
            }
        claims = tuple(state.get("claims", ()))
        candidates = tuple(item for item in claims if item.get("status") == "candidate")
        accepted = tuple(item for item in claims if item.get("status") == "accepted")
        if not claims:
            return {
                "key": "input",
                "stage": "第 1 步 / 4",
                "title": "补充一句目标或问题",
                "body": "当前只读到了文本片段，还没有形成可确认的候选内容。",
                "action_label": "补充需求",
                "action_url": f"{root}/input",
                "steps": (("输入需求", "current"), ("确认理解", "waiting"), ("生成正式 RFLP", "waiting"), ("项目验证", "optional")),
            }
        if candidates:
            return {
                "key": "review",
                "stage": "第 2 步 / 4",
                "title": "确认系统对你的理解",
                "body": f"系统识别了 {len(claims)} 条候选，其中 {len(candidates)} 条还没有确认。确认后才会进入正式 RFLP。",
                "action_label": "去确认需求",
                "action_url": f"{root}/review",
                "steps": (("输入需求", "done"), ("确认理解", "current"), ("生成正式 RFLP", "waiting"), ("项目验证", "optional")),
            }
        if accepted and (not state.get("rflp") or state.get("draft")):
            return {
                "key": "formal",
                "stage": "第 3 步 / 4",
                "title": "生成正式 RFLP",
                "body": f"已有 {len(accepted)} 条需求确认，可以生成正式的 Requirement → Function → Logical → Physical 模型。",
                "action_label": "生成正式 RFLP",
                "action_url": f"{root}/graph",
                "steps": (("输入需求", "done"), ("确认理解", "done"), ("生成正式 RFLP", "current"), ("项目验证", "optional")),
            }
        if state.get("rflp") and not state.get("baseline"):
            return {
                "key": "baseline",
                "stage": "第 4 步 / 4",
                "title": "批准模型并进入项目验证",
                "body": "正式 RFLP 已生成。批准后才能拿它和本地项目进行实现差异分析。",
                "action_label": "进入项目验证",
                "action_url": f"/w/{workspace_name}/project",
                "steps": (("输入需求", "done"), ("确认理解", "done"), ("生成正式 RFLP", "done"), ("项目验证", "current")),
            }
        return {
            "key": "complete",
            "stage": "当前阶段已完成",
            "title": "需求模型已建立",
            "body": "当前需求已经形成正式模型。你可以继续补充场景，或在项目验证中检查实际实现。",
            "action_label": "查看正式 RFLP",
            "action_url": f"{root}/graph",
            "steps": (("输入需求", "done"), ("确认理解", "done"), ("生成正式 RFLP", "done"), ("项目验证", "optional")),
        }

    @staticmethod
    def _requirement_records_for_state(
        state: dict[str, object], event: str
    ) -> tuple[dict[str, object], ...]:
        artifact = state.get("artifact") or {}
        spans = {
            str(item.get("id")): item for item in state.get("spans", ())
        }
        records = []
        for claim in state.get("claims", ()):
            span = spans.get(str(claim.get("span_id")), {})
            records.append(
                {
                    "id": str(claim["id"]),
                    "subject": claim.get("subject", ""),
                    "predicate": claim.get("predicate", ""),
                    "object": claim.get("object", ""),
                    "status": claim.get("status", "candidate"),
                    "source_type": claim.get("source_type", "provisional"),
                    "candidate_type": claim.get("candidate_type", ""),
                    "interpretation": claim.get("interpretation", ""),
                    "confidence": claim.get("confidence", 0.0),
                    "span_id": claim.get("span_id", ""),
                    "source_text": span.get("text", claim.get("object", "")),
                    "source_locator": span.get("locator", claim.get("span_id", "")),
                    "artifact": artifact.get("path", ""),
                    "artifact_sha256": artifact.get("sha256", ""),
                    "last_event": event,
                }
            )
        return tuple(records)

    def requirement_overview(self, workspace_name: str) -> dict[str, object]:
        """Return the project-level requirement ledger and status counts."""
        workspace = self.workspace(workspace_name)
        state = self.requirements(workspace_name)
        repository = SQLiteRepository(workspace.path / ".rflp" / "model.db")
        try:
            records = repository.requirement_records()
        finally:
            repository.close()

        # Workspaces created before the ledger table existed still get a useful
        # overview immediately; the next write permanently backfills the rows.
        if not records and state is not None:
            records = self._requirement_records_for_state(state, "requirements.current")
        current_ids = {
            str(item["id"]) for item in (state or {}).get("claims", ())
        }
        labels = {
            "candidate": "待确认",
            "accepted": "已接受",
            "rejected": "已驳回",
        }
        source_labels = {
            "need": "利益相关方需求",
            "constraint": "约束 / 质量属性",
            "goal": "系统目标",
            "problem": "问题 / 痛点",
            "provisional": "待分类输入",
        }
        items = []
        for item in records:
            record = dict(item)
            status = str(record.get("status", "candidate"))
            record["status_label"] = labels.get(status, status)
            record["source_label"] = source_labels.get(
                str(record.get("source_type", "")), "自然语言输入"
            )
            record["is_current"] = str(record.get("id")) in current_ids
            items.append(record)
        counts = {status: 0 for status in ("candidate", "accepted", "rejected")}
        for item in items:
            status = str(item.get("status", "candidate"))
            if status in counts:
                counts[status] += 1
        return {
            "total": len(items),
            "submitted": len(items),
            "current": sum(bool(item["is_current"]) for item in items),
            "counts": counts,
            "items": tuple(items),
        }

    def analyze_requirements(
        self,
        workspace_name: str,
        filename: str,
        content: bytes,
        merge: bool = False,
    ) -> dict[str, object]:
        workspace = self.workspace(workspace_name)
        filename = Path(filename).name
        current = self.requirements(workspace_name)
        if merge and current is not None:
            state = merge_artifact(current, filename, content)
        else:
            state = analyze_artifact(filename, content)
            if current is not None:
                manual_names = {
                    item["name"].casefold()
                    for item in current.get("stakeholders", ())
                    if item.get("candidate_type") == "manual"
                }
                detected_names = {
                    item["name"].casefold() for item in state["stakeholders"]
                }
                state["stakeholders"].extend(
                    item
                    for item in current.get("stakeholders", ())
                    if item.get("candidate_type") == "manual"
                    and item["name"].casefold() not in detected_names
                    and item["name"].casefold() in manual_names
                )
                state["stakeholders"] = sorted(
                    state["stakeholders"],
                    key=lambda item: (item["name"], item["id"]),
                )
        if state.get("spans"):
            # Always leave a visible, local RFLP draft after submission. The
            # draft is intentionally separate from formal review/baselining.
            state = generate_draft_model(state)
        safe_name = state["artifact"]["path"]
        inputs = workspace.path / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        (inputs / f'{state["artifact"]["sha256"][:12]}-{safe_name}').write_bytes(content)
        repository = SQLiteRepository(workspace.path / ".rflp" / "model.db")
        try:
            with repository.transaction():
                repository.save_workbench(state)
                event = "requirements.merged" if merge else "requirements.analyzed"
                sequence = repository.record_audit(
                    event,
                    {"artifact": safe_name, "sha256": state["artifact"]["sha256"]},
                )
                repository.save_requirement_records(
                    self._requirement_records_for_state(state, event), sequence, event
                )
        finally:
            repository.close()
        return state

    def review_requirement_item(
        self,
        workspace_name: str,
        group: str,
        item_id: str,
        status: str,
        value: str,
        category: str = "",
    ) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            raise ContractViolation("requirements workbench is empty")
        return self._save_requirements(
            workspace_name,
            review_item(current, group, item_id, status, value, category),
            "requirements.reviewed",
        )

    def add_requirement_stakeholder(
        self, workspace_name: str, name: str, category: str = ""
    ) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            current = empty_workbench()
        return self._save_requirements(
            workspace_name,
            add_stakeholder(current, name, category),
            "stakeholder.added",
        )

    def stakeholder_categories(self) -> tuple[tuple[str, str], ...]:
        return STAKEHOLDER_CATEGORIES

    def requirement_stakeholder_bundle(
        self, workspace_name: str, name: str = ""
    ) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            return stakeholder_bundle({"stakeholders": []}, name)
        return stakeholder_bundle(current, name)

    def accept_traceable_requirements(self, workspace_name: str) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            raise ContractViolation("requirements workbench is empty")
        return self._save_requirements(
            workspace_name, confirm_requirements(current), "requirements.accepted"
        )

    def generate_requirements_model(self, workspace_name: str) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            raise ContractViolation("requirements workbench is empty")
        current = confirm_requirements(current)
        return self._save_requirements(
            workspace_name, generate_model(current), "requirements.generated"
        )

    def confirm_and_generate_requirements(self, workspace_name: str) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            raise ContractViolation("requirements workbench is empty")
        confirmed = confirm_requirements(current)
        return self._save_requirements(
            workspace_name,
            generate_model(confirmed),
            "requirements.confirmed_and_generated",
        )

    def generate_requirements_draft(self, workspace_name: str) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            raise ContractViolation("requirements workbench is empty")
        return self._save_requirements(
            workspace_name,
            generate_draft_model(current),
            "requirements.draft_generated",
        )

    def run_requirements_flow(self, workspace_name: str) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            raise ContractViolation("请先在需求输入中提交需求")
        return self._save_requirements(
            workspace_name,
            run_requirements_flow(current),
            "requirements.flow_completed",
        )

    def analyze_requirements_with_ai(self, workspace_name: str) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            raise ContractViolation("requirements workbench is empty")
        return self._save_requirements(
            workspace_name,
            add_llm_suggestions(current, self.llm.active_config()),
            "requirements.ai_suggested",
        )

    def add_requirement_scenario(
        self,
        workspace_name: str,
        *,
        title: str,
        description: str,
        actors: str = "",
        preconditions: str = "",
        steps: str,
        expected_outcomes: str,
        faults: str = "",
        requirement_ids: str = "",
    ) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            current = empty_workbench()
        state = add_scenario(
            current,
            title=title,
            description=description,
            actors=actors,
            preconditions=preconditions,
            steps=steps,
            expected_outcomes=expected_outcomes,
            faults=faults,
            requirement_ids=requirement_ids,
        )
        return self._save_requirements(
            workspace_name, state, "scenario.created"
        )

    def prepare_requirement_scenarios(
        self, workspace_name: str
    ) -> dict[str, object] | None:
        """Make system-generated starter scenarios available without extra input."""
        current = self.requirements(workspace_name)
        if current is None or current.get("scenarios"):
            return current
        state = generate_scenario_drafts(current)
        if not state.get("scenarios"):
            return state
        return self._save_requirements(
            workspace_name,
            state,
            "scenario.generated",
            {"count": len(state["scenarios"]), "mode": "minimum-input"},
        )

    def delete_requirement_scenario(
        self, workspace_name: str, scenario_id: str
    ) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            raise ContractViolation("requirements workbench is empty")
        return self._save_requirements(
            workspace_name,
            delete_scenario(current, scenario_id),
            "scenario.deleted",
        )

    def execute_requirement_scenario(
        self, workspace_name: str, scenario_id: str
    ) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            raise ContractViolation("requirements workbench is empty")
        workspace = self.workspace(workspace_name)
        jobs = JobService(workspace.path)
        job = jobs.submit(
            "scenario.execute",
            {"scenario_id": scenario_id},
            lambda: execute_scenario(current, scenario_id),
        )
        result = job["result"]
        updated = append_scenario_run(current, result)
        updated = self._save_requirements(
            workspace_name,
            updated,
            "scenario.executed",
            {"scenario_id": scenario_id, "run_id": result["run_id"], "status": result["status"]},
        )
        return {**result, "job": {"id": job["id"], "status": job["status"]}}

    def scenario_runs(self, workspace_name: str) -> tuple[dict[str, object], ...]:
        state = self.requirements(workspace_name)
        if state is None:
            raise ContractViolation("requirements workbench is empty")
        return tuple(state.get("scenario_runs", ()))

    def job(self, workspace_name: str, job_id: str) -> dict[str, object] | None:
        return JobService(self.workspace(workspace_name).path).get(job_id)

    def approve_requirements_baseline(self, workspace_name: str) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            raise ContractViolation("requirements workbench is empty")
        state, baseline = approve_workbench_baseline(current)
        workspace = self.workspace(workspace_name)
        repository = SQLiteRepository(workspace.path / ".rflp" / "model.db")
        try:
            with repository.transaction():
                repository.save_workbench(state)
                repository.save_baseline(baseline)
                repository.record_audit(
                    "baseline.approved", {"baseline_hash": baseline.hash}
                )
        finally:
            repository.close()
        return state

    def analyze_workspace_project(
        self, workspace_name: str, source: str
    ) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            raise ContractViolation("requirements workbench is empty")
        state, artifacts = analyze_project_state(current, source)
        workspace = self.workspace(workspace_name)
        repository = SQLiteRepository(workspace.path / ".rflp" / "model.db")
        try:
            with repository.transaction():
                repository.save_workbench(state)
                repository.save_baseline(artifacts.baseline)
                repository.save_evidence(artifacts.evidence)
                repository.save_tasks(artifacts.tasks)
                repository.record_audit(
                    "project.analyzed",
                    {
                        "source": str(state["project"]["source"]),
                        "missing": sum(
                            1 for item in artifacts.delta.items if item.kind == "MISSING"
                        ),
                        "extra": sum(
                            1 for item in artifacts.delta.items if item.kind == "EXTRA"
                        ),
                        "tasks": len(artifacts.tasks),
                    },
                )
        finally:
            repository.close()
        return state

    def verify_workspace_project(
        self, workspace_name: str, source: str
    ) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            raise ContractViolation("requirements workbench is empty")
        state, verify = verify_contracts_state(current, source)
        summary = state["project"]["execution"]["summary"]
        workspace = self.workspace(workspace_name)
        repository = SQLiteRepository(workspace.path / ".rflp" / "model.db")
        try:
            with repository.transaction():
                repository.save_workbench(state)
                repository.save_evidence(verify.evidence)
                repository.record_audit(
                    "project.executed",
                    {
                        "source": str(state["project"]["execution"]["source"]),
                        "resolved": summary["resolved"],
                        "unresolved": summary["unresolved"],
                        "missing": summary["missing"],
                        "extra": summary["extra"],
                    },
                )
        finally:
            repository.close()
        return state

    def test_workspace_project(
        self,
        workspace_name: str,
        *,
        runners: tuple[str, ...] = ("pytest",),
        limits: ResourceLimits | None = None,
        jobs: int = 1,
        use_cache: bool = True,
    ) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            raise ContractViolation("requirements workbench is empty")
        project = current.get("project")
        if not project or not project.get("source"):
            raise ContractViolation("请先在项目接入中分析项目")
        workspace = self.workspace(workspace_name)
        cache_dir = workspace.path / ".rflp" / "test-cache" if use_cache else None
        state, verify = execute_tests_state(
            current,
            project["source"],
            runners=runners,
            limits=limits,
            cache_dir=cache_dir,
            jobs=jobs,
        )
        test_run = state["project"]["execution"]["summary"]["test_run"]
        repository = SQLiteRepository(workspace.path / ".rflp" / "model.db")
        try:
            with repository.transaction():
                repository.save_workbench(state)
                repository.save_evidence(verify.evidence)
                repository.record_audit(
                    "project.tested",
                    {
                        "source": str(state["project"]["execution"]["source"]),
                        "returncode": test_run["returncode"],
                        "timed_out": test_run["timed_out"],
                        "tests_passed": test_run["tests_passed"],
                        "tests_failed": test_run["tests_failed"],
                        "runner": test_run["runner"],
                        "cache_hit": test_run["cache_hit"],
                    },
                )
        finally:
            repository.close()
        return state

    def _save_requirements(
        self,
        workspace_name: str,
        state: dict[str, object],
        event: str,
        audit_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        workspace = self.workspace(workspace_name)
        repository = SQLiteRepository(workspace.path / ".rflp" / "model.db")
        try:
            with repository.transaction():
                repository.save_workbench(state)
                sequence = repository.record_audit(
                    event,
                    audit_payload or {"artifact": state["artifact"]["path"]},
                )
                repository.save_requirement_records(
                    self._requirement_records_for_state(state, event), sequence, event
                )
        finally:
            repository.close()
        return state

    def dashboard(self, workspace_name: str | None) -> dict[str, object]:
        workspaces = self.workspaces()
        if workspace_name is None:
            if not workspaces:
                return {
                    "workspace": None,
                    "workspaces": (),
                    "latest_run": None,
                    "counts": {},
                    "audit": (),
                    "requirements_guide": self.requirements_guide(workspace_name) if workspace_name else None,
                    "requirements_overview": {
                        "total": 0,
                        "submitted": 0,
                        "current": 0,
                        "counts": {"candidate": 0, "accepted": 0, "rejected": 0},
                        "items": (),
                    },
                }
            workspace_name = workspaces[0].name
        workspace = self.workspace(workspace_name)
        runs = self.runs(workspace_name)
        latest = runs[0] if runs else None
        if latest is None:
            counts: dict[str, int] = {}
        else:
            outputs = latest.outputs
            model = outputs.get("rflp.json", {})
            elements = model.get("elements", []) if isinstance(model, dict) else []
            counts = {
                "claims": len(outputs.get("claims.json", [])),
                "R": sum(item.get("layer") == "R" for item in elements),
                "F": sum(item.get("layer") == "F" for item in elements),
                "L": sum(item.get("layer") == "L" for item in elements),
                "P": sum(item.get("layer") == "P" for item in elements),
                "candidates": len(outputs.get("candidates.json", [])),
                "tasks": len(outputs.get("task-contracts.json", [])),
                "evidence": len(outputs.get("evidence.json", [])),
            }
        return {
            "workspace": workspace,
            "workspaces": workspaces,
            "latest_run": latest,
            "counts": counts,
            "audit": self.audit(workspace_name),
            "requirements_guide": self.requirements_guide(workspace_name),
            "requirements_overview": self.requirement_overview(workspace_name),
        }
