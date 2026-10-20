from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pytest

from camera_assistant.services.timing import current_stage, measure_stage, observe_timings


def test_start_notification_arrives_before_work_and_keeps_duration_contract():
    events = []
    durations = []
    with (observe_timings(durations.append, on_started=events.append),
          measure_stage("composition_contours")):
        assert events == ["composition_contours"]
        assert current_stage() == "composition_contours"
        assert durations == []
    assert durations[0]["status"] == "complete"
    assert set(durations[0]) == {"stage", "duration_seconds", "status"}
    assert current_stage() is None


def test_feedback_failure_cannot_abort_work_and_nested_observers_are_restored():
    events = []

    def broken_feedback(stage):
        raise RuntimeError("display unavailable")

    with observe_timings(lambda event: None, on_started=events.append):
        with (observe_timings(lambda event: None, on_started=broken_feedback),
              measure_stage("vision")):
            assert current_stage() == "vision"
        with measure_stage("composition_contours"):
            pass
    with measure_stage("outside_request"):
        pass
    assert events == ["composition_contours"]


def test_parallel_branches_receive_start_events_and_failures_remain_failures():
    started = []
    finished = []

    def work(stage):
        with measure_stage(stage):
            assert current_stage() == stage
            if stage == "composition_contours":
                raise ValueError("synthetic contour failure")

    with (observe_timings(finished.append, on_started=started.append),
          ThreadPoolExecutor(max_workers=2) as executor):
        parameters = executor.submit(copy_context().run, work, "parameters")
        contours = executor.submit(copy_context().run, work, "composition_contours")
        parameters.result()
        with pytest.raises(ValueError, match="synthetic contour failure"):
            contours.result()
    assert set(started) == {"parameters", "composition_contours"}
    assert {item["stage"]: item["status"] for item in finished} == {
        "parameters": "complete", "composition_contours": "failed",
    }
