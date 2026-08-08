from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rflp_lite.application.scenario_execution import execute_scenario
from rflp_lite.domain.errors import ContractViolation


PluginHandler = Callable[[dict[str, object]], dict[str, object]]


@dataclass(frozen=True, slots=True)
class Plugin:
    name: str
    version: str
    description: str
    handler: PluginHandler

    def metadata(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "execution": "in-process",
            "status": "available",
        }


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    def register(
        self,
        name: str,
        handler: PluginHandler,
        *,
        version: str = "0.1",
        description: str = "local plugin",
    ) -> dict[str, object]:
        clean_name = name.strip()
        if not clean_name:
            raise ContractViolation("plugin name cannot be empty")
        self._plugins[clean_name] = Plugin(clean_name, version, description, handler)
        return self._plugins[clean_name].metadata()

    def list(self) -> tuple[dict[str, object], ...]:
        return tuple(self._plugins[name].metadata() for name in sorted(self._plugins))

    def invoke(self, name: str, payload: dict[str, object]) -> dict[str, object]:
        plugin = self._plugins.get(name)
        if plugin is None:
            raise ContractViolation(f"plugin not found: {name}")
        try:
            result = plugin.handler(payload)
            if not isinstance(result, dict):
                raise TypeError("plugin handler must return an object")
            return {"status": "ok", "plugin": name, "result": result}
        except Exception as exc:
            return {
                "status": "failed",
                "plugin": name,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }


def _scenario_plugin(payload: dict[str, object]) -> dict[str, object]:
    state = payload.get("state")
    scenario_id = payload.get("scenario_id")
    if not isinstance(state, dict) or not isinstance(scenario_id, str):
        raise ContractViolation("scenario plugin requires state and scenario_id")
    return execute_scenario(state, scenario_id)


DEFAULT_REGISTRY = PluginRegistry()
DEFAULT_REGISTRY.register(
    "scenario-trace",
    _scenario_plugin,
    description="generate a declarative scenario trace without executing code",
)


def register_plugin(
    name: str,
    handler: PluginHandler,
    *,
    version: str = "0.1",
    description: str = "local plugin",
) -> dict[str, object]:
    return DEFAULT_REGISTRY.register(name, handler, version=version, description=description)


def list_plugins() -> tuple[dict[str, object], ...]:
    return DEFAULT_REGISTRY.list()


def invoke_plugin(name: str, payload: dict[str, object]) -> dict[str, Any]:
    return DEFAULT_REGISTRY.invoke(name, payload)
