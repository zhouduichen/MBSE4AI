from __future__ import annotations

from pathlib import Path

from rflp_lite.adapters.sqlite_repository import SQLiteRepository
from rflp_lite.application.demo import run_demo
from rflp_lite.application.run_catalog import RunRecord, list_runs, load_run
from rflp_lite.application.requirements_workbench import (
    accept_traceable,
    add_llm_suggestions,
    analyze_artifact,
    generate_model,
    review_item,
)
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
        self, workspace_name: str, filename: str, content: bytes
    ) -> dict[str, object]:
        workspace = self.workspace(workspace_name)
        state = analyze_artifact(Path(filename).name, content)
        safe_name = state["artifact"]["path"]
        inputs = workspace.path / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        (inputs / f'{state["artifact"]["sha256"][:12]}-{safe_name}').write_bytes(content)
        repository = SQLiteRepository(workspace.path / ".rflp" / "model.db")
        try:
            with repository.transaction():
                repository.save_workbench(state)
                repository.record_audit(
                    "requirements.analyzed",
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
