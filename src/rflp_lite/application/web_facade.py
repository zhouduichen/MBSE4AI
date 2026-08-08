from __future__ import annotations

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
    accept_traceable,
    add_llm_suggestions,
    analyze_artifact,
    generate_model,
    merge_artifact,
    review_item,
)
from rflp_lite.application.scenarios import add_scenario, delete_scenario
from rflp_lite.application.workspaces import (
    WorkspaceRef,
    create_managed_workspace,
    list_managed_workspaces,
    managed_workspace,
)
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.governance.profile import Profile


class WebFacade:
    def __init__(self, workspace_root: Path, fixture_root: Path | None = None):
        self.workspace_root = workspace_root.resolve()
        self.fixture_root = fixture_root

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
            return repository.load_workbench()
        finally:
            repository.close()

    def analyze_requirements(
        self,
        workspace_name: str,
        filename: str,
        content: bytes,
        merge: bool = False,
    ) -> dict[str, object]:
        workspace = self.workspace(workspace_name)
        filename = Path(filename).name
        current = self.requirements(workspace_name) if merge else None
        if current is not None:
            state = merge_artifact(current, filename, content)
        else:
            state = analyze_artifact(filename, content)
        safe_name = state["artifact"]["path"]
        inputs = workspace.path / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        (inputs / f'{state["artifact"]["sha256"][:12]}-{safe_name}').write_bytes(content)
        repository = SQLiteRepository(workspace.path / ".rflp" / "model.db")
        try:
            with repository.transaction():
                repository.save_workbench(state)
                repository.record_audit(
                    "requirements.merged" if merge else "requirements.analyzed",
                    {"artifact": safe_name, "sha256": state["artifact"]["sha256"]},
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
    ) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            raise ContractViolation("requirements workbench is empty")
        return self._save_requirements(
            workspace_name,
            review_item(current, group, item_id, status, value),
            "requirements.reviewed",
        )

    def accept_traceable_requirements(self, workspace_name: str) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            raise ContractViolation("requirements workbench is empty")
        return self._save_requirements(
            workspace_name, accept_traceable(current), "requirements.accepted"
        )

    def generate_requirements_model(self, workspace_name: str) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            raise ContractViolation("requirements workbench is empty")
        return self._save_requirements(
            workspace_name, generate_model(current), "requirements.generated"
        )

    def analyze_requirements_with_ai(self, workspace_name: str) -> dict[str, object]:
        current = self.requirements(workspace_name)
        if current is None:
            raise ContractViolation("requirements workbench is empty")
        return self._save_requirements(
            workspace_name, add_llm_suggestions(current), "requirements.ai_suggested"
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
            raise ContractViolation("requirements workbench is empty")
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
        self, workspace_name: str, state: dict[str, object], event: str
    ) -> dict[str, object]:
        workspace = self.workspace(workspace_name)
        repository = SQLiteRepository(workspace.path / ".rflp" / "model.db")
        try:
            with repository.transaction():
                repository.save_workbench(state)
                repository.record_audit(event, {"artifact": state["artifact"]["path"]})
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
        }
