from pathlib import Path
import json

from rflp_lite.application.web_facade import WebFacade


def test_empty_dashboard_is_honest(tmp_path: Path) -> None:
    facade = WebFacade(tmp_path / "workspaces")
    view = facade.dashboard(None)
    assert view["workspace"] is None
    assert view["latest_run"] is None
    assert view["counts"] == {}


def test_project_summaries_list_all_managed_projects(tmp_path: Path) -> None:
    facade = WebFacade(tmp_path / "workspaces")
    facade.create_workspace("alpha")
    facade.create_workspace("beta")

    summaries = facade.project_summaries()

    assert [item["workspace"].name for item in summaries] == ["alpha", "beta"]
    assert all(item["requirements"] == () for item in summaries)


def test_facade_creates_workspace_and_executes_both_solvers(tmp_path: Path) -> None:
    facade = WebFacade(tmp_path / "workspaces")
    facade.create_workspace("demo")
    heuristic = facade.execute("demo", "heuristic", 42)
    cp_sat = facade.execute("demo", "cp-sat", 42)
    assert heuristic.manifest["status"] == "passed"
    assert cp_sat.manifest["status"] == "passed"
    assert heuristic.result_hash != cp_sat.result_hash
    assert heuristic.manifest["baseline_hash"] == cp_sat.manifest["baseline_hash"]


def test_facade_concept_design_import_run_and_review(tmp_path: Path) -> None:
    facade = WebFacade(tmp_path / "workspaces")
    facade.create_workspace("concept")
    pack = Path("src/rflp_lite/resources/domain-packs/fixed-wing-v1.json")
    examples = Path("src/rflp_lite/resources/examples/concept-design")
    imported = facade.import_concept_schemes(
        "concept", pack, (examples / "fixed-wing-schemes.json").read_bytes(), "schemes.json"
    )
    assert len(imported["records"]) == 4
    envelope = json.loads((examples / "fixed-wing-envelope.json").read_text(encoding="utf-8"))
    profile = {
        "id": "customer-approved",
        "version": 1,
        "approvals": {
            adapter_id: {
                "adapter_version": "1",
                "approved_for_formal": True,
                "basis": "test approval",
            }
            for adapter_id in (
                "builtin.aerodynamics.v1",
                "builtin.structures.v1",
                "builtin.weight-balance.v1",
            )
        },
    }
    result = facade.run_concept_design("concept", pack, profile, envelope)
    assert result["status"] == "completed"
    review = facade.review_layout_candidate(
        "concept", result["candidates"][0]["id"], "accepted", result["id"]
    )
    assert review["decision"] == "accepted"
    assert facade.concept_run("concept", result["id"])["id"] == result["id"]
