from tests.interface.web.test_requirements_workbench import _client_with_fixture


def test_assurance_behavior_operational_and_history_pages_are_available(tmp_path):
    client, _ = _client_with_fixture(tmp_path)
    for path in ("/projects/p1/operational", "/projects/p1/behavior", "/projects/p1/assurance", "/projects/p1/history", "/ui/projects/p1/operational", "/ui/projects/p1/behavior", "/ui/projects/p1/assurance", "/ui/projects/p1/history"):
        assert client.get(path).status_code == 200
