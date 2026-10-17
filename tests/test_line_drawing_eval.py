from __future__ import annotations

import http.client
import json
import socket
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from line_drawing_eval.acceptance import PRIORITY, budget_plan, build_matrix
from line_drawing_eval.cli import main
from line_drawing_eval.evidence import RunLayout, discover_runs, index_run
from line_drawing_eval.gallery import build_gallery, render_board_svg
from line_drawing_eval.ledger import BudgetError, GateError, Ledger
from line_drawing_eval.serve import create_server
from line_drawing_eval.timing import analyze_run


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _run_fixture(root: Path, *, case_id: str = "02") -> RunLayout:
    run_dir = root / "live-run-1" / case_id
    photo = root / "photo.jpg"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(b"stub")
    summary = {
        "case_id": case_id,
        "success": True,
        "gateway_analysis_posts": 1,
        "source_fingerprint": "abc",
        "http_status": 200,
        "seconds": 30.2,
        "analysis_mode": "cloud",
        "trace_id": "trace",
        "diagnostics": [
            {"stage": "recognition", "status": "complete", "code": "objects_validated"}
        ],
        "timings": [
            {"stage": "image_preprocessing", "duration_seconds": 0.1},
            {"stage": "vision", "duration_seconds": 10.0},
            {"stage": "parameters", "duration_seconds": 20.0},
            {"stage": "composition", "duration_seconds": 15.0},
            {"stage": "total", "duration_seconds": 30.1},
        ],
        "first_events_seconds": {"composition_ready": 20.0, "result": 30.2},
        "internal_cloud_request_starts_total": 4,
    }
    events = [
        {"type": "activity", "stage": "parameters", "phase": "request_started",
         "client_seconds": 10.0, "chars": 0},
        {"type": "activity", "stage": "parameters", "phase": "content",
         "client_seconds": 15.0, "chars": 5},
        {"type": "activity", "stage": "parameters", "phase": "content",
         "client_seconds": 23.0, "chars": 100},
        {"type": "activity", "stage": "parameters", "phase": "finished",
         "client_seconds": 23.2, "chars": 100, "complete": True, "streamed": True},
    ]
    _write(run_dir / "summary.json", summary)
    _write(run_dir / "events.json", events)
    _write(run_dir / "result.json", {
        "result": {
            "scene": {"scene_label": "测试场景", "subject": "狗", "lighting": "日光"},
            "recommendation": {"shutter_speed": "1/1000s", "reasons": ["保持动作清晰"]},
            "composition": {
                "status": "ok",
                "proposals": [{
                    "goal": "保持主体",
                    "storyboard": {"layers": [{
                        "bbox": [0.1, 0.1, 0.9, 0.9],
                        "outline": [[0, 0], [1, 0], [1, 1], [0, 1]],
                        "holes": [[[0.4, 0.4], [0.6, 0.4], [0.6, 0.6]]],
                        "details": [],
                    }]},
                }],
            },
        }
    })
    _write(run_dir.parent / "run_manifest.json", {
        "samples": [{
            "id": case_id,
            "title": "测试",
            "photos": [str(photo)],
            "sha256": "nope",
            "intent": "测试意图",
            "request": {"intent": "测试意图"},
        }],
        "configuration": {"image_provenance": "original_upload"},
    })
    return RunLayout(root=run_dir, run="live-run-1", case_id=case_id)


def test_timing_uses_max_for_parallel_branches(tmp_path: Path) -> None:
    layout = _run_fixture(tmp_path)
    timing = analyze_run(layout.root, run=layout.run, case_id=layout.case_id)
    assert timing["predicted_total_seconds"] == pytest.approx(30.1)
    assert timing["measured_total_seconds"] == pytest.approx(30.1)
    assert timing["critical_branch"] == "parameters"
    assert timing["ready_lead_seconds"] == pytest.approx(10.2)
    call = timing["cloud_calls"][0]
    assert call["time_to_first_content_seconds"] == pytest.approx(5.0)
    assert call["generation_seconds"] == pytest.approx(8.0)


def test_index_flags_unrecorded_model_and_mask(tmp_path: Path) -> None:
    layout = _run_fixture(tmp_path)
    record = index_run(layout)
    assert record["offline"] is True
    assert record["generated_model_requests"] == 0
    assert record["device"]["model"] == "unrecorded_in_run_manifest"
    assert record["masks"]["raw_mask_saved"] is False
    assert record["original"]["sha256_matches"] is False
    assert discover_runs(tmp_path)[0].case_id == "02"


def test_index_writes_one_directory_per_attempt(tmp_path: Path) -> None:
    _run_fixture(tmp_path / "evidence")
    out = tmp_path / "records"
    assert main(["index", "--evidence", str(tmp_path / "evidence"), "--out", str(out)]) == 0
    record = json.loads(
        (out / "runs" / "live-run-1-02" / "run-record.json").read_text(encoding="utf-8")
    )
    assert record["offline"] is True
    assert record["generated_model_requests"] == 0
    assert record["timing"]["critical_branch"] == "parameters"
    assert "raw boolean mask" in record["masks"]["note"]


def test_ledger_counts_before_sending_and_refuses_overdraft(tmp_path: Path) -> None:
    ledger = Ledger.create_inherited(tmp_path / "ledger.json", {"attempts": []})
    assert ledger.remaining == 3
    for index in range(3):
        ledger.reserve(f"0{index}", "test")
    assert ledger.remaining == 0
    with pytest.raises(BudgetError):
        ledger.reserve("08", "must not silently extend budget")


def test_ledger_detects_arithmetic_drift(tmp_path: Path) -> None:
    ledger = Ledger.create_inherited(tmp_path / "ledger.json", {"attempts": []})
    ledger.data["budget"]["remaining_gateway_posts"] = 8
    with pytest.raises(ValueError):
        ledger.validate()


def test_live_gate_requires_explicit_flag_and_integration_ready(tmp_path: Path) -> None:
    ledger = Ledger.create_inherited(tmp_path / "ledger.json", {"attempts": []})
    gate = tmp_path / "INTEGRATION_READY.json"
    with pytest.raises(GateError):
        ledger.require_live_allowed(explicit_live=False, integration_gate=gate)
    with pytest.raises(GateError):
        ledger.require_live_allowed(explicit_live=True, integration_gate=gate)
    gate.write_text(json.dumps({
        "status": "INTEGRATION_READY", "commit": "abc", "port": 8093, "pid": 1,
        "built_assets": "index.js", "frozen_at": "now",
    }), encoding="utf-8")
    ledger.require_live_allowed(explicit_live=True, integration_gate=gate)
    while ledger.remaining:
        ledger.reserve("02", "test")
    with pytest.raises(BudgetError):
        ledger.require_live_allowed(explicit_live=True, integration_gate=gate)


def test_acceptance_starts_unverified_and_orders_by_risk() -> None:
    matrix = build_matrix()
    assert [case["case_id"] for case in matrix["cases"]] == ["02", "06", "07", "08"]
    assert all(case["status"] == "not_tested" and case["passed"] is False
               for case in matrix["cases"])
    plan = budget_plan(3)
    assert plan["planned_order"] == ["06", "07", "02"]
    assert plan["unfunded"] == ["08"]
    assert plan["minimum_gap_for_four_cases"] == 1
    assert PRIORITY[0] == "06"


def test_gallery_is_script_free_and_marks_replay(tmp_path: Path) -> None:
    layout = _run_fixture(tmp_path / "evidence")
    receipt = build_gallery([layout], tmp_path / "gallery")
    page = Path(receipt["page"]).read_text(encoding="utf-8")
    assert "<script" not in page.lower()
    assert "离线回放" in page
    assert receipt["generated_model_requests"] == 0
    assert "<svg" in page and "evenodd" in page


def test_board_svg_keeps_holes_evenodd() -> None:
    svg = render_board_svg({"layers": [{
        "bbox": [0, 0, 1, 1],
        "outline": [[0, 0], [1, 0], [1, 1], [0, 1]],
        "holes": [[[0.2, 0.2], [0.4, 0.2], [0.4, 0.4]]],
        "details": [],
    }]})
    assert 'fill-rule="evenodd"' in svg
    assert svg.count("M ") == 2


def test_replay_server_rejects_posts(tmp_path: Path) -> None:
    layout = _run_fixture(tmp_path / "evidence")
    gallery_dir = tmp_path / "gallery"
    build_gallery([layout], gallery_dir)
    server = create_server(gallery_dir, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        probe = socket.socket()
        try:
            probe.settimeout(1)
            probe.connect((host, port))
        except PermissionError:
            pytest.skip("sandbox blocks loopback connections; run the browser replay proof escalated")
        finally:
            probe.close()
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request("GET", "/gallery.html")
        assert connection.getresponse().status == 200
        connection.request("POST", "/api/analyze", body=b"{}")
        assert connection.getresponse().status == 403
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
    log = (gallery_dir / "access.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(json.loads(line)["kind"] == "blocked_post" for line in log)
