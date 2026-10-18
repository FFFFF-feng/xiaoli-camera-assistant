"""Request-scoped, content-free composition stage evidence."""
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar

from camera_assistant.composition_models import CompositionDiagnostic

_sink: ContextVar[Callable[[CompositionDiagnostic], None] | None] = ContextVar("composition_trace", default=None)
_trace: ContextVar[str | None] = ContextVar("composition_request_trace", default=None)


def current_trace_id():
    return _trace.get()


@contextmanager
def observe_diagnostics(callback, *, trace_id=None):
    token = _sink.set(callback)
    trace_token = _trace.set(trace_id)
    try:
        yield
    finally:
        _sink.reset(token)
        _trace.reset(trace_token)


def stage_result(stage, status, code, *, object_id=None, field_path=None, segmentation=None):
    sink = _sink.get()
    if sink:
        sink(CompositionDiagnostic(stage=stage, status=status, code=code,
                                   object_id=object_id, field_path=field_path, segmentation=segmentation))
