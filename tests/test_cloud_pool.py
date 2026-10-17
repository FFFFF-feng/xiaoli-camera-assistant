from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import Barrier, Event

import httpx
import pytest
from test_cloud_transport import settings

from camera_assistant.services import cloud


def recorded_clients(monkeypatch, handler):
    """Keep real client lifecycle and request construction; replace only network I/O."""
    original_client = httpx.Client
    clients = []

    class RecordingClient(original_client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)
            self.close_count = 0
            clients.append(self)

        def close(self):
            self.close_count += 1
            super().close()

    monkeypatch.setattr(httpx, "Client", RecordingClient)
    return clients


def answer(content='{"ok":true}'):
    return httpx.Response(200, json={"choices": [{
        "finish_reason": "stop", "message": {"content": content},
    }]})


def test_session_reuses_client_for_serial_requests_and_format_retry(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return answer('{"ok":true}}' if len(requests) == 1 else '{"ok":true}')

    clients = recorded_clients(monkeypatch, handler)
    with cloud.cloud_session(settings()):
        assert cloud.request_json(settings(), {}) == {"ok": True}
        assert cloud.request_json(settings(), {}) == {"ok": True}
        assert len(clients) == 1
        assert not clients[0].is_closed
        assert clients[0].close_count == 0
    assert len(requests) == 3
    assert clients[0].is_closed
    assert clients[0].close_count == 1


def test_parallel_contexts_share_one_session_client(monkeypatch):
    both_started = Barrier(2)

    def handler(request):
        both_started.wait(timeout=3)
        return answer()

    clients = recorded_clients(monkeypatch, handler)
    with cloud.cloud_session(settings()), ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(copy_context().run, cloud.request_json, settings(), {})
                   for _ in range(2)]
        assert [future.result(timeout=5) for future in futures] == [{"ok": True}, {"ok": True}]
        assert len(clients) == 1
        assert not clients[0].is_closed
    assert clients[0].close_count == 1


def test_settings_and_nested_analysis_keep_per_request_credentials_and_timeouts(monkeypatch):
    requests = []

    def handler(request):
        requests.append((str(request.url), request.headers["Authorization"],
                         request.extensions["timeout"]))
        return answer()

    clients = recorded_clients(monkeypatch, handler)
    first = settings(api_key="first-private-key", timeout_seconds=17)
    second = settings(api_key="second-private-key", base_url="https://second.invalid/v2",
                      timeout_seconds=23)
    with cloud.cloud_session(first):
        cloud.request_json(first, {})
        cloud.request_json(second, {})
        with cloud.cloud_session(second):
            cloud.request_json(second, {})
        assert len(clients) == 2 and clients[1].is_closed
        assert not clients[0].is_closed
        cloud.request_json(first, {})
    with cloud.cloud_session(second):
        cloud.request_json(second, {})
    assert len(clients) == 3
    assert [row[1] for row in requests] == [
        "Bearer first-private-key", "Bearer second-private-key", "Bearer second-private-key",
        "Bearer first-private-key", "Bearer second-private-key",
    ]
    assert [row[0] for row in requests] == [
        "https://example.invalid/v1/chat/completions",
        "https://second.invalid/v2/chat/completions", "https://second.invalid/v2/chat/completions",
        "https://example.invalid/v1/chat/completions", "https://second.invalid/v2/chat/completions",
    ]
    assert [row[2]["read"] for row in requests] == [17, 23, 23, 17, 23]
    assert all("Authorization" not in client.headers for client in clients)
    assert all(client.close_count == 1 for client in clients)


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
def test_service_failure_is_not_retried_and_session_is_closed(monkeypatch, failure):
    requests = []

    def handler(request):
        requests.append(request)
        raise failure("private provider detail", request=request)

    clients = recorded_clients(monkeypatch, handler)
    with pytest.raises(cloud.ModelServiceError), cloud.cloud_session(settings()):
        cloud.request_json(settings(), {})
    assert len(requests) == 1
    assert len(clients) == 1 and clients[0].is_closed
    assert clients[0].close_count == 1


def test_session_exit_waits_for_an_inflight_paid_request(monkeypatch):
    started, release, exiting = Event(), Event(), Event()

    def handler(request):
        started.set()
        assert release.wait(timeout=5)
        return answer()

    clients = recorded_clients(monkeypatch, handler)
    workers = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        def owner():
            with cloud.cloud_session(settings()):
                workers.append(pool.submit(copy_context().run, cloud.request_json, settings(), {}))
                assert started.wait(timeout=3)
                exiting.set()
                raise ValueError("analysis aborted")

        owner_future = pool.submit(owner)
        assert exiting.wait(timeout=3)
        try:
            with pytest.raises(TimeoutError):
                owner_future.result(timeout=.05)
            assert not clients[0].is_closed
        finally:
            release.set()
        with pytest.raises(ValueError, match="analysis aborted"):
            owner_future.result(timeout=3)
        assert workers[0].result(timeout=3) == {"ok": True}
    assert clients[0].is_closed and clients[0].close_count == 1


def test_calls_without_session_keep_independent_client_lifecycle(monkeypatch):
    clients = recorded_clients(monkeypatch, lambda request: answer())
    cloud.request_json(settings(), {})
    cloud.request_json(settings(), {})
    assert len(clients) == 2
    assert all(client.is_closed for client in clients)


def test_session_with_no_cloud_calls_closes_on_body_failure(monkeypatch):
    clients = recorded_clients(monkeypatch, lambda request: pytest.fail("unexpected paid request"))
    with pytest.raises(ValueError, match="local failure"), cloud.cloud_session(settings()):
        raise ValueError("local failure")
    assert len(clients) == 1 and clients[0].close_count == 1


def test_parallel_failure_releases_lease_and_waits_for_remaining_paid_branch(monkeypatch):
    both_started, release, exiting = Barrier(2), Event(), Event()
    workers = []

    def handler(request):
        both_started.wait(timeout=3)
        if json.loads(request.content)["model"] == "failed":
            raise httpx.ConnectError("private remote detail", request=request)
        assert release.wait(timeout=5)
        return answer()

    clients = recorded_clients(monkeypatch, handler)
    with ThreadPoolExecutor(max_workers=3) as pool:
        def owner():
            with cloud.cloud_session(settings()):
                for branch in ("failed", "remaining"):
                    workers.append(pool.submit(copy_context().run, cloud.request_json,
                                               settings(), {"model": branch}))
                try:
                    workers[0].result(timeout=3)
                finally:
                    exiting.set()

        owner_future = pool.submit(owner)
        assert exiting.wait(timeout=3)
        try:
            with pytest.raises(TimeoutError):
                owner_future.result(timeout=.05)
            assert not clients[0].is_closed
        finally:
            release.set()
        with pytest.raises(cloud.ModelServiceError, match="无法连接"):
            owner_future.result(timeout=3)
        assert workers[1].result(timeout=3) == {"ok": True}
    assert clients[0].is_closed and clients[0].close_count == 1


def test_context_copied_before_session_close_gets_a_fresh_client(monkeypatch):
    clients = recorded_clients(monkeypatch, lambda request: answer())
    with cloud.cloud_session(settings()):
        expired_context = copy_context()
    assert clients[0].is_closed
    assert expired_context.run(cloud.request_json, settings(), {}) == {"ok": True}
    assert len(clients) == 2
    assert clients[1].is_closed


def test_streaming_calls_and_format_retry_share_client_until_session_exit(monkeypatch):
    from test_cloud_streaming import stream_response, successful_stream

    streams, requests = [], []

    def handler(request):
        requests.append(request)
        content = '{"ok":true}}' if len(requests) == 1 else '{"ok":true}'
        response, stream = stream_response(successful_stream(content))
        streams.append(stream)
        return response

    clients = recorded_clients(monkeypatch, handler)
    events = []
    with cloud.cloud_session(settings()), cloud.observe_stream(events.append):
        assert cloud.request_json(settings(), {}) == {"ok": True}
        assert cloud.request_json(settings(timeout_seconds=27), {}) == {"ok": True}
        assert len(clients) == 1 and not clients[0].is_closed
        assert all(stream.closed for stream in streams)
    assert len(requests) == 3
    assert all(json.loads(request.content)["stream"] is True for request in requests)
    assert [request.extensions["timeout"]["read"] for request in requests] == [120, 120, 27]
    assert all(event["streamed"] for event in events if event["phase"] == "finished")
    assert clients[0].close_count == 1


def test_stage_timings_record_complete_and_failed_with_nested_context(monkeypatch):
    from camera_assistant.services import timing

    observed = []
    ticks = iter([1.0, 2.0, 2.5, 4.0, 6.0, 7.0])
    monkeypatch.setattr(timing.time, "monotonic", lambda: next(ticks))
    assert timing.current_stage() is None
    with timing.observe_timings(observed.append):
        with timing.measure_stage("total"):
            assert timing.current_stage() == "total"
            with timing.measure_stage("vision"):
                assert timing.current_stage() == "vision"
            assert timing.current_stage() == "total"
        with pytest.raises(ValueError), timing.measure_stage("parameters"):
            raise ValueError("private prompt and credentials")
    assert timing.current_stage() is None
    assert observed == [
        {"stage": "vision", "duration_seconds": .5, "status": "complete"},
        {"stage": "total", "duration_seconds": 3.0, "status": "complete"},
        {"stage": "parameters", "duration_seconds": 1.0, "status": "failed"},
    ]


def test_timing_observers_restore_and_do_not_interrupt_analysis():
    from camera_assistant.services import timing

    first, second = [], []

    def broken(event):
        raise RuntimeError("display disconnected")

    with timing.observe_timings(first.append), timing.measure_stage("vision"):
        with timing.observe_timings(second.append), timing.measure_stage("localization"):
            pass
        with timing.observe_timings(broken), timing.measure_stage("composition"):
            pass
    with timing.measure_stage("outside"):
        pass
    assert [event["stage"] for event in first] == ["vision"]
    assert [event["stage"] for event in second] == ["localization"]
    assert all(event["duration_seconds"] >= 0 for event in first + second)


def test_timing_context_is_propagated_to_parallel_branches_without_crossing_analyses():
    from camera_assistant.services import timing

    first, second = [], []
    both_started = Barrier(2)

    def branch(stage):
        with timing.measure_stage(stage):
            both_started.wait(timeout=3)
            assert timing.current_stage() == stage

    with ThreadPoolExecutor(max_workers=2) as pool:
        with timing.observe_timings(first.append), timing.measure_stage("first"):
            first_context = copy_context()
        with timing.observe_timings(second.append), timing.measure_stage("second"):
            second_context = copy_context()
        futures = [pool.submit(first_context.run, branch, "vision"),
                   pool.submit(second_context.run, branch, "composition")]
        for future in futures:
            future.result(timeout=5)
    assert [event["stage"] for event in first] == ["first", "vision"]
    assert [event["stage"] for event in second] == ["second", "composition"]
    assert timing.current_stage() is None


def test_cloud_progress_includes_only_current_stage_metadata(monkeypatch):
    from camera_assistant.services import timing

    recorded_clients(monkeypatch, lambda request: answer())
    events = []
    with cloud.observe_stream(events.append), timing.measure_stage("vision"):
        assert cloud.request_json(settings(), {"messages": [
            {"role": "user", "content": "private prompt secret-test-only"},
        ]}) == {"ok": True}
    assert [event["phase"] for event in events] == ["request_started", "content", "finished"]
    assert all(event["stage"] == "vision" for event in events)
    assert events[-1]["first_content_seconds"] >= 0
    assert "private" not in json.dumps(events)
    assert "secret-test-only" not in json.dumps(events)
