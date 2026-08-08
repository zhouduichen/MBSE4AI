from __future__ import annotations

import pytest

from rflp_lite.application.plugins import PluginRegistry, list_plugins
from rflp_lite.domain.errors import ContractViolation


def test_registry_discovers_and_invokes_in_process_plugin():
    registry = PluginRegistry()
    registered = registry.register("echo", lambda payload: {"value": payload["value"]})

    assert registered["execution"] == "in-process"
    assert registry.invoke("echo", {"value": 3}) == {
        "status": "ok",
        "plugin": "echo",
        "result": {"value": 3},
    }


def test_registry_returns_structured_handler_failure():
    registry = PluginRegistry()
    registry.register("broken", lambda payload: (_ for _ in ()).throw(ValueError("bad")))

    result = registry.invoke("broken", {})

    assert result["status"] == "failed"
    assert result["error"]["message"] == "bad"


def test_registry_rejects_unknown_plugin():
    with pytest.raises(ContractViolation, match="not found"):
        PluginRegistry().invoke("missing", {})


def test_default_registry_exposes_only_local_scenario_plugin():
    assert list_plugins()[0]["name"] == "scenario-trace"
