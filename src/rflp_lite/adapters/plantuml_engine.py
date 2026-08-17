"""Optional PlantUML pipe renderer for sequence and activity sources."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Callable, Sequence

from rflp_lite.ports.diagram_engine import DiagramRenderResult


Runner = Callable[..., subprocess.CompletedProcess[bytes]]


def _parts(command: str | Sequence[str] | None, default: str) -> list[str]:
    if command is None:
        command = os.getenv("AI4MBSE_PLANTUML_CMD", default)
    if isinstance(command, str):
        values = shlex.split(command)
    else:
        values = [str(item) for item in command]
    return values or [default]


class PlantUMLEngine:
    engine_id = "plantuml"

    def __init__(
        self,
        command: str | Sequence[str] | None = None,
        runner: Runner = subprocess.run,
    ) -> None:
        self.command = _parts(command, "plantuml")
        self.runner = runner

    def status(self) -> dict[str, object]:
        executable = self.command[0]
        resolved = executable if os.path.isabs(executable) else shutil.which(executable)
        return {
            "engine_id": self.engine_id,
            "available": bool(resolved),
            "executable": resolved or executable,
            "formats": ("svg", "png"),
        }

    def render(
        self, source: str, output_format: str = "svg", timeout_seconds: int = 10
    ) -> DiagramRenderResult:
        if output_format not in {"svg", "png"}:
            return DiagramRenderResult(self.engine_id, False, b"", "", "PlantUML 只支持 svg 或 png")
        if not self.status()["available"]:
            return DiagramRenderResult(self.engine_id, False, b"", "", "PlantUML 命令不可用")
        args = [*self.command, "-pipe", f"-t{output_format}"]
        try:
            completed = self.runner(
                args,
                input=source.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=max(1, min(int(timeout_seconds), 60)),
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return DiagramRenderResult(self.engine_id, False, b"", "", "PlantUML 渲染超时")
        except (FileNotFoundError, OSError) as exc:
            return DiagramRenderResult(self.engine_id, False, b"", "", f"PlantUML 执行失败: {exc}")
        diagnostic = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
        if completed.returncode != 0 or not completed.stdout:
            return DiagramRenderResult(
                self.engine_id,
                False,
                b"",
                "",
                diagnostic or f"PlantUML 返回码 {completed.returncode}",
            )
        media_type = "image/svg+xml" if output_format == "svg" else "image/png"
        return DiagramRenderResult(self.engine_id, True, bytes(completed.stdout), media_type, diagnostic)
