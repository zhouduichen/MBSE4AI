from tests.interface.web.test_requirements_workbench import _client_with_fixture


def test_traceability_and_rflp_views_agree_on_complete_fixture(tmp_path):
    client, requirement_id = _client_with_fixture(tmp_path)
    matrix = client.get("/projects/p1/traceability").json()
    row = next(item for item in matrix["rows"] if item["requirement_id"] == requirement_id)
    assert row["coverage_percent"] == 100.0
    focused = client.get(f"/projects/p1/rflp/trace/{requirement_id}").json()
    assert focused["selected_trace"][0] == requirement_id
    assert focused["selected_trace"][1:] == [row["functions"][0], row["logical_components"][0], row["physical_blocks"][0]]
    assert focused["gaps"] == []
    assert client.get(f"/ui/projects/p1/rflp?requirement_id={requirement_id}").status_code == 200
