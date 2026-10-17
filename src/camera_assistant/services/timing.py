"""Opt-in stage duration metadata, scoped to one analysis context."""
from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar

_observer: ContextVar[Callable[[dict], None] | None] = ContextVar(
    "analysis_timing_observer", default=None,
)
_stage: ContextVar[str | None] = ContextVar("analysis_current_stage", default=None)


@contextmanager
def observe_timings(callback: Callable[[dict], None]):
    """Receive stage, duration_seconds and status; never receive analysis content."""
    token = _observer.set(callback)
    try:
        yield
    finally:
        _observer.reset(token)


def current_stage() -> str | None:
    return _stage.get()


@contextmanager
def measure_stage(stage: str):
    """Measure completion or failure without letting an observer abort analysis."""
    started = time.monotonic()
    token = _stage.set(stage)
    status = "failed"
    try:
        yield
        status = "complete"
    finally:
        duration = time.monotonic() - started
        _stage.reset(token)
        observer = _observer.get()
        if observer is not None:
            try:
                observer({"stage": stage, "duration_seconds": duration, "status": status})
            except Exception:  # noqa: BLE001, S110 - display failures must not abort paid analysis
                pass
