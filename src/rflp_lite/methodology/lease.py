"""Small lease helpers for long-running provider calls."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import threading


@contextmanager
def heartbeat_scope(
    heartbeat: Callable[[], None],
    *,
    interval_seconds: float = 30.0,
) -> Iterator[None]:
    """Keep a run lease alive while a blocking provider call is in flight.

    The callback is invoked once before entering the scope and then from a
    daemon thread.  A failed heartbeat is re-raised after the provider call,
    so callers cannot accidentally commit a response produced after lease
    ownership was lost.
    """

    heartbeat()
    stopped = threading.Event()
    failures: list[Exception] = []

    def _loop() -> None:
        while not stopped.wait(max(0.1, float(interval_seconds))):
            try:
                heartbeat()
            except Exception as exc:  # pragma: no cover - timing dependent
                failures.append(exc)
                stopped.set()
                return

    worker = threading.Thread(
        target=_loop,
        name="rflp-run-lease-heartbeat",
        daemon=True,
    )
    worker.start()
    try:
        yield
    finally:
        stopped.set()
        worker.join(timeout=max(1.0, float(interval_seconds)))
    if failures:
        raise failures[0]


__all__ = ["heartbeat_scope"]
