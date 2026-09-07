import json
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "campus_delivery_robot.json"


def test_campus_delivery_robot_fixture_has_lifecycle_and_failure_coverage():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert fixture["lifecycle_stages"] == ["规划", "部署", "运行", "维护", "退役"]
    assert "通信丢失恢复" in fixture["scenarios"]
    assert {item["id"] for item in fixture["requirements"]} == {
        "req-availability",
        "req-maintenance",
    }
