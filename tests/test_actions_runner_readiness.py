from __future__ import annotations

from scripts import actions_runner_readiness as readiness


def test_evaluate_runner_targets_requires_online_matching_labels() -> None:
    payload = {
        "runners": [
            {
                "name": "offline-full",
                "status": "offline",
                "busy": False,
                "labels": [{"name": label} for label in ("self-hosted", "llm", "gpu")],
            },
            {
                "name": "online-llm",
                "status": "online",
                "busy": True,
                "labels": [{"name": label} for label in ("self-hosted", "llm")],
            },
        ]
    }

    result = readiness.evaluate_runner_targets(
        payload,
        (
            ("remote-llm", ("self-hosted", "llm")),
            ("gpu", ("self-hosted", "gpu")),
        ),
    )

    assert result["available"] is False
    assert result["targets"]["remote-llm"]["available"] is True
    assert result["targets"]["remote-llm"]["matches"][0]["busy"] is True
    assert result["targets"]["gpu"]["available"] is False


def test_wait_for_runner_targets_polls_until_online() -> None:
    payloads = [
        {"runners": []},
        {
            "runners": [
                {
                    "name": "remote-bridge",
                    "status": "online",
                    "busy": False,
                    "labels": [{"name": label} for label in ("self-hosted", "llm")],
                }
            ]
        },
    ]
    sleeps: list[float] = []

    def fetch(_api_url: str, _token: str):
        return payloads.pop(0)

    clock_values = iter((0.0, 0.0, 1.0))

    result = readiness.wait_for_runner_targets(
        "https://api.github.test/runners",
        "token",
        (("remote-llm", ("self-hosted", "llm")),),
        timeout_seconds=20,
        poll_seconds=5,
        fetch=fetch,
        sleep=sleeps.append,
        clock=lambda: next(clock_values),
    )

    assert result["available"] is True
    assert result["attempts"] == 2
    assert sleeps == [5.0]


def test_parse_target_rejects_missing_labels() -> None:
    try:
        readiness.parse_target("gpu=")
    except ValueError as exc:
        assert "at least one label" in str(exc)
    else:
        raise AssertionError("missing runner labels must fail closed")
