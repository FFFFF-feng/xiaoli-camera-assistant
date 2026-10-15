from __future__ import annotations

import json

import httpx
import pytest
from test_cloud_transport import settings, transport

from camera_assistant.services import cloud


def test_response_observer_keeps_safe_metadata_and_original_response(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={
        "choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}],
        "usage": {"prompt_tokens": 123, "completion_tokens": 5, "total_tokens": 128},
    }))
    events = []
    with cloud.observe_responses(events.append):
        assert cloud.request_json(settings(), {"messages": [{"role": "user", "content": "你好"}]}) == {"ok": True}
    assert events[0]["finish_reason"] == "stop"
    assert events[0]["usage"]["prompt_tokens"] == 123
    assert events[0]["response_content"] == '{"ok":true}'
    assert events[0]["request_text_chars"] == 2
    assert events[0]["seconds"] >= 0
    assert "secret-test-only" not in json.dumps(events)


def test_truncated_response_is_observable_without_becoming_a_valid_answer(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={
        "choices": [{"finish_reason": "length", "message": {"content": '{"partial":'}}],
        "usage": {"completion_tokens": 4096},
    }))
    events = []
    with cloud.observe_responses(events.append), pytest.raises(cloud.ModelServiceError, match="截断"):
        cloud.request_json(settings(), {})
    assert len(events) == 1
    assert events[0]["response_content"] == '{"partial":'
    assert events[0]["finish_reason"] == "length"


def test_timeout_observer_cannot_leak_remote_exception_details(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("secret-test-only", request=request)
    transport(monkeypatch, fail)
    events = []
    with cloud.observe_responses(events.append), pytest.raises(cloud.ModelServiceError, match="超时"):
        cloud.request_json(settings(), {})
    assert events[0]["error_category"] == "timeout"
    assert events[0]["finish_reason"] is None
    assert "secret-test-only" not in json.dumps(events)
