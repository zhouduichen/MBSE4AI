from tests.interface.web.test_requirements_workbench import _client_with_fixture


def test_rflp_api_and_svg_are_deterministic_engineering_views(tmp_path):
    client, requirement_id = _client_with_fixture(tmp_path)
    first = client.get("/projects/p1/rflp", params={"requirement_id": requirement_id}).json()
    second = client.get("/projects/p1/rflp", params={"requirement_id": requirement_id}).json()
    assert first == second
    assert first["selected_trace"][0] == requirement_id
    svg = client.get("/projects/p1/rflp.svg", params={"requirement_id": requirement_id})
    assert svg.status_code == 200
    assert svg.headers["content-type"].startswith("image/svg+xml")
    assert "RFLP architecture trace" in svg.text
