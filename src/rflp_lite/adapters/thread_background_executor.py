"""Small local background executor for at-least-once jobs."""

from __future__ import annotations

import threading
from collections.abc import Callable


class ThreadBackgroundExecutor:
    def submit(self, job_id: str, runner: Callable[[], None]) -> None:
        thread = threading.Thread(
            target=runner,
            name=f"rflp-job-{job_id}",
            daemon=True,
        )
        thread.start()
