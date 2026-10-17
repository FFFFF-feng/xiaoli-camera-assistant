from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import httpx
import pytest
from test_cloud_transport import settings, transport

from camera_assistant.services import cloud


class ByteChunks(httpx.SyncByteStream):
    """Exercise httpx's real incremental UTF-8 and SSE line decoding offline."""

    def __init__(self, content: bytes, *, chunk_size: int = 3, failure=None):
        self.content = content
        self.chunk_size = chunk_size
        self.failure = failure
        self.closed = False

    def __iter__(self):
        for start in range(0, len(self.content), self.chunk_size):
            yield self.content[start:start + self.chunk_size]
        if self.failure is not None:
            raise self.failure("private remote detail secret-test-only")

    def close(self):
        self.closed = True


def frame(data: dict, *, multiline=False) -> str:
    value = json.dumps(data, ensure_ascii=False)
    if multiline:
        value = value.replace(', "choices"', ',\n"choices"')
    return "".join(f"data: {line}\r\n" for line in value.splitlines()) + "\r\n"


def delta(content=None, *, finish=None, **updates):
    return {"choices": [{"index": 0, "delta": {"content": content, **updates},
                         "finish_reason": finish}]}


def stream_response(content: str, **updates):
    stream = ByteChunks(content.encode("utf-8"), **updates)
    response = httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)
    return response, stream


def successful_stream(content='{"ok":true}'):
    return frame(delta(content)) + frame(delta(finish="stop")) + "data: [DONE]\n\n"


def test_incremental_sse_unicode_multiline_usage_and_safe_progress(monkeypatch):
    sent = []
    raw = (
        ": keepalive\r\n\r\n"
        + frame(delta(reasoning_content="private reasoning secret-test-only"))
        + frame(delta('{"建议":"'))
        + frame(delta('拍摄"}'))
        + frame(delta(finish="stop"))
        + frame({"id": "remote-private-id", "choices": [], "usage": {
            "prompt_tokens": 42, "completion_tokens": 9, "total_tokens": 51,
            "private": "secret-test-only",
        }}, multiline=True)
        + "data: [DONE]\r\n\r\n"
    )
    response, byte_stream = stream_response(raw, chunk_size=1)

    def handler(request):
        sent.append(json.loads(request.content))
        return response

    transport(monkeypatch, handler)
    progress, evidence = [], []
    with cloud.observe_stream(progress.append), cloud.observe_responses(evidence.append):
        assert cloud.request_json(settings(), {"stream": False}) == {"建议": "拍摄"}
    assert len(sent) == 1 and sent[0]["stream"] is True
    assert byte_stream.closed
    assert [event["phase"] for event in progress] == [
        "request_started", "content", "content", "finished",
    ]
    assert [event["chars"] for event in progress] == [0, 7, 11, 11]
    assert len({event["request_id"] for event in progress}) == 1
    assert progress[-1]["complete"] is True
    assert progress[-1]["streamed"] is True
    assert progress[-1]["first_content_seconds"] >= 0
    assert evidence[0]["request_id"] == progress[0]["request_id"]
    assert evidence[0]["response_content"] == '{"建议":"拍摄"}'
    assert evidence[0]["usage"] == {
        "prompt_tokens": 42, "completion_tokens": 9, "total_tokens": 51,
    }
    assert evidence[0]["finish_reason"] == "stop"
    assert evidence[0]["seconds"] >= evidence[0]["first_content_seconds"] >= 0
    assert "拍摄" not in json.dumps(progress, ensure_ascii=False)
    assert "private" not in json.dumps(progress + evidence)
    assert "secret-test-only" not in json.dumps(progress + evidence)


@pytest.mark.parametrize("finish", ["length", "content_filter", "sensitive"])
def test_stream_truncation_and_filter_are_not_format_retried(monkeypatch, finish):
    calls, progress, evidence = [], [], []

    def handler(request):
        calls.append(request)
        return stream_response(frame(delta('{"ok":true}', finish=finish)))[0]

    transport(monkeypatch, handler)
    with (cloud.observe_stream(progress.append), cloud.observe_responses(evidence.append),
          pytest.raises(cloud.ModelServiceError)):
        cloud.request_json(settings(), {})
    assert len(calls) == 1
    assert evidence[0]["response_content"] == '{"ok":true}'
    assert evidence[0]["finish_reason"] == finish
    assert progress[-1]["complete"] is False
    assert progress[-1]["error_category"] == (
        "truncated" if finish == "length" else "refusal"
    )


@pytest.mark.parametrize("raw", [
    frame(delta(refusal="private remote detail secret-test-only")),
    frame({"error": {"message": "private remote detail secret-test-only"}}),
    "event: error\ndata: private remote detail secret-test-only\n\n",
    "data: invalid remote JSON secret-test-only\n\n",
])
def test_stream_refusal_error_and_invalid_envelope_are_safe_and_not_retried(monkeypatch, raw):
    calls, progress = [], []

    def handler(request):
        calls.append(request)
        return stream_response(raw)[0]

    transport(monkeypatch, handler)
    with cloud.observe_stream(progress.append), pytest.raises(cloud.ModelServiceError) as error:
        cloud.request_json(settings(), {})
    assert len(calls) == 1
    assert progress[-1]["complete"] is False
    assert "secret-test-only" not in str(error.value) + json.dumps(progress)
    assert "private remote detail" not in str(error.value) + json.dumps(progress)


@pytest.mark.parametrize("raw", [
    frame(delta('{"ok":true}')),
    frame(delta('{"ok":true}', finish="stop")),
    frame(delta('{"ok":true}', finish="stop")) + "data: [DONE]",
    frame(delta('{"ok":true}')) + "data: [DONE]\n\n",
    frame(delta('{"ok":true}', finish="tool_calls")) + "data: [DONE]\n\n",
    "data: [DONE]\n\n",
])
def test_valid_json_without_both_stop_and_done_is_incomplete(monkeypatch, raw):
    calls, progress, evidence = [], [], []

    def handler(request):
        calls.append(request)
        return stream_response(raw)[0]

    transport(monkeypatch, handler)
    with (cloud.observe_stream(progress.append), cloud.observe_responses(evidence.append),
          pytest.raises(cloud.ModelServiceError, match="未完成")):
        cloud.request_json(settings(), {})
    assert len(calls) == 1
    assert progress[-1]["complete"] is False
    assert evidence[0]["error_category"] == "stream_incomplete"


@pytest.mark.parametrize("failure,category,match", [
    (httpx.ReadTimeout, "timeout", "超时"),
    (httpx.ReadError, "connection", "无法连接"),
])
def test_partial_stream_timeout_and_interruption_are_not_retried(
    monkeypatch, failure, category, match,
):
    calls, progress, evidence = [], [], []
    raw = frame(delta('{"ok":true}', finish="stop"))

    def handler(request):
        calls.append(request)
        return stream_response(raw, failure=failure)[0]

    transport(monkeypatch, handler)
    with (cloud.observe_stream(progress.append), cloud.observe_responses(evidence.append),
          pytest.raises(cloud.ModelServiceError, match=match) as error):
        cloud.request_json(settings(), {})
    assert len(calls) == 1
    assert evidence[0]["response_content"] == '{"ok":true}'
    assert evidence[0]["error_category"] == category
    assert progress[-1]["complete"] is False
    assert "secret-test-only" not in str(error.value) + json.dumps(progress + evidence)


def test_provider_ignoring_stream_uses_same_json_response(monkeypatch):
    sent, progress, evidence = [], [], []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}],
            "usage": {"total_tokens": 19},
        })

    transport(monkeypatch, handler)
    with cloud.observe_stream(progress.append), cloud.observe_responses(evidence.append):
        assert cloud.request_json(settings(), {}) == {"ok": True}
    assert len(sent) == 1 and sent[0]["stream"] is True
    assert evidence[0]["streamed"] is False
    assert evidence[0]["usage"] == {"total_tokens": 19}
    assert progress[-1]["complete"] is True
    assert progress[-1]["streamed"] is False


def test_unsupported_stream_http_error_does_not_make_paid_fallback_request(monkeypatch):
    sent, progress = [], []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, text="stream unsupported secret-test-only")

    transport(monkeypatch, handler)
    with cloud.observe_stream(progress.append), pytest.raises(cloud.ModelServiceError, match="400"):
        cloud.request_json(settings(), {})
    assert len(sent) == 1 and sent[0]["stream"] is True
    assert progress[-1]["error_category"] == "http_status"
    assert "secret-test-only" not in json.dumps(progress)


def test_only_complete_stream_reaches_json_validation_and_bounded_format_retry(monkeypatch):
    calls, validated, evidence = [], [], []
    real_extract = cloud.extract_json

    def extract(content):
        validated.append(content)
        return real_extract(content)

    def handler(request):
        calls.append(request)
        content = '{"ok":true}}' if len(calls) == 1 else '{"ok":true}'
        return stream_response(successful_stream(content))[0]

    transport(monkeypatch, handler)
    monkeypatch.setattr(cloud, "extract_json", extract)
    with (cloud.observe_stream(lambda _: None), cloud.observe_responses(evidence.append)):
        assert cloud.request_json(settings(), {}) == {"ok": True}
    assert len(calls) == 2
    assert validated == ['{"ok":true}}', '{"ok":true}']
    assert len({event["request_id"] for event in evidence}) == 2


def test_stream_context_is_nested_scoped_and_default_remains_non_stream(monkeypatch):
    sent, outer, inner = [], [], []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        return (stream_response(successful_stream())[0] if body["stream"] else httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok":true}'}}]},
        ))

    transport(monkeypatch, handler)
    with cloud.observe_stream(outer.append):
        cloud.request_json(settings(), {})
        with cloud.observe_stream(inner.append):
            cloud.request_json(settings(), {})
        cloud.request_json(settings(), {})
    cloud.request_json(settings(), {})
    assert [body["stream"] for body in sent] == [True, True, True, False]
    assert len({event["request_id"] for event in outer}) == 2
    assert len({event["request_id"] for event in inner}) == 1
    assert not ({event["request_id"] for event in outer}
                & {event["request_id"] for event in inner})


def test_copied_context_propagates_observers_to_parallel_workers(monkeypatch):
    progress, evidence = [], []
    transport(monkeypatch, lambda request: stream_response(successful_stream())[0])
    with (cloud.observe_stream(progress.append), cloud.observe_responses(evidence.append),
          ThreadPoolExecutor(max_workers=2) as pool):
        contexts = [copy_context(), copy_context()]
        futures = [pool.submit(context.run, cloud.request_json, settings(), {})
                   for context in contexts]
        assert [future.result() for future in futures] == [{"ok": True}, {"ok": True}]
    assert len(evidence) == 2
    assert len({event["request_id"] for event in progress}) == 2
    assert len([event for event in progress if event["phase"] == "finished"]) == 2


def test_progress_callback_failure_does_not_interrupt_model_request(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return stream_response(successful_stream())[0]

    def fail(_):
        raise RuntimeError("display unavailable")

    transport(monkeypatch, handler)
    with cloud.observe_stream(fail):
        assert cloud.request_json(settings(), {}) == {"ok": True}
    assert len(calls) == 1
