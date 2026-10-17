"""Request-scoped, content-free composition stage evidence."""
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar

from camera_assistant.composition_models import CompositionDiagnostic

_sink: ContextVar[Callable[[CompositionDiagnostic], None] | None] = ContextVar("composition_trace", default=None)


@contextmanager
def observe_diagnostics(callback):
    token = _sink.set(callback)
    try:
        yield
    finally:
        _sink.reset(token)


def stage_result(stage, status, code):
    sink = _sink.get()
    if sink:
        sink(CompositionDiagnostic(stage=stage, status=status, code=code))
