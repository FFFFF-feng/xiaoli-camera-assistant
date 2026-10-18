from __future__ import annotations

import http.client
import json
import socket
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from line_drawing_eval.acceptance import PRIORITY, budget_plan, build_matrix
from line_drawing_eval.cli import main
from line_drawing_eval.evidence import RunLayout, discover_runs, index_run
from line_drawing_eval.gallery import build_gallery, render_board_svg
from line_drawing_eval.ledger import BudgetError, GateError, Ledger
from line_drawing_eval.live import analyze_case, load_cases, run_batch, summarize
from line_drawing_eval.preflight import PreflightError, source_fingerprint, verify
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


class _FakeResponse:
    def __init__(self, payload=None, lines=None, status_code=200):
        self._payload = payload or {}
        self._lines = lines or []
        self.status_code = status_code
        self.headers = {"content-type": "application/x-ndjson"}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload

    def iter_lines(self):
        return iter(self._lines)


class _FakeClient:
    def __init__(self, lines):
        self.lines = lines
        self.posts = 0

    def get(self, path):
        return _FakeResponse({"service": "xiaoli-mobile-api", "analysis_mode": "cloud"})

    def post(self, path):
        self.posts += 1
        return _FakeResponse()

    @contextmanager
    def stream(self, method, path, **kwargs):
        yield _FakeResponse(lines=self.lines)

    def close(self):
        return None


def _ndjson() -> list[bytes]:
    return [
        json.dumps({"type": "timing", "stage": "vision", "duration_seconds": 2.0,
                    "status": "complete", "elapsed_seconds": 2.0}).encode(),
        json.dumps({"type": "activity", "stage": "vision", "phase": "request_started",
                    "chars": 0}).encode(),
        json.dumps({"type": "activity", "stage": "composition_observation",
                    "phase": "request_started", "chars": 0}).encode(),
        json.dumps({"type": "activity", "stage": "composition_observation",
                    "phase": "request_started", "chars": 0}).encode(),
        json.dumps({"type": "partial", "kind": "composition_ready",
                    "value": {"status": "ok",
                              "proposals": [{"goal": "g", "storyboard": {"layers": []}}]}}).encode(),
        json.dumps({"type": "result", "timings": [],
                    "result": {
                        "scene": {"scene_label": "测试"},
                        "recommendation": {"shutter_speed": "1/500s"},
                        "composition": {
                            "status": "ok",
                            "proposals": [{"goal": "g", "storyboard": {"layers": []}}],
                        },
                    }}).encode(),
    ]


def test_analyze_case_parses_ndjson_without_retry(tmp_path: Path) -> None:
    case = {"id": "02", "photo": str(tmp_path / "p.jpg"), "sha256": "abc", "request": {}}
    (tmp_path / "p.jpg").write_bytes(b"stub")
    client = _FakeClient(_ndjson())
    row = analyze_case(client, case, tmp_path / "run" / "02")
    assert row["success"] is True
    assert row["gateway_analysis_posts"] == 1
    assert row["internal_cloud_request_starts_total"] == 3
    assert row["observation_protocol_repairs"] == 1
    assert row["backend_board_count"] == 1
    assert row["ready_matches_final"] is True
    assert client.posts == 1  # only /session; analyze is streamed once


def test_summarize_reports_missing_final_and_ready_mismatch() -> None:
    row = summarize(None, case_id="07", sample_sha256="x", seconds=1.0, events=[], ready=None)
    assert row["failure_code"] == "connection_ended_without_final"
    mismatch = summarize(
        {"result": {"scene": {}, "recommendation": {}, "composition": {"proposals": []}}},
        case_id="07", sample_sha256="x", seconds=1.0, events=[],
        ready={"status": "different"},
    )
    assert mismatch["ready_matches_final"] is False


def test_load_cases_rejects_photo_hash_mismatch(tmp_path: Path) -> None:
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"stub")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"samples": [{
        "id": "02", "photos": [str(photo)], "sha256": "wrong", "request": {},
    }]}), encoding="utf-8")
    with pytest.raises(ValueError, match="hash differs"):
        load_cases(manifest, ["02"])


def test_run_batch_refuses_short_budget_before_any_run(tmp_path: Path, monkeypatch) -> None:
    ledger = Ledger.create_inherited(tmp_path / "ledger.json", {"attempts": []})
    ledger.save()
    gate = tmp_path / "gate.json"
    gate.write_text("{}", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    photos = []
    samples = []
    for case_id in ("02", "06", "07", "08"):
        photo = tmp_path / f"{case_id}.jpg"
        photo.write_bytes(b"stub")
        samples.append({"id": case_id, "photos": [str(photo)], "sha256": "0" * 64, "request": {}})
        photos.append(photo)
    manifest.write_text(json.dumps({"samples": samples}), encoding="utf-8")
    # Use the real load_cases hash check by writing matching hashes.
    import hashlib
    for sample, photo in zip(samples, photos):
        sample["sha256"] = hashlib.sha256(photo.read_bytes()).hexdigest()
    manifest.write_text(json.dumps({"samples": samples}), encoding="utf-8")
    monkeypatch.setattr(
        "line_drawing_eval.live.verify",
        lambda *a, **k: {"gate": str(gate), "origin": "http://127.0.0.1:9",
                         "source_fingerprint": {}, "health": {}},
    )
    with pytest.raises(BudgetError):
        run_batch(
            gate_path=gate, ledger_path=tmp_path / "ledger.json", manifest_path=manifest,
            out_root=tmp_path / "out", run_name="e2-test",
            case_ids=["02", "06", "07", "08"], client_factory=lambda origin: _FakeClient([]),
        )
    assert not (tmp_path / "out").exists()


def test_run_batch_reserves_and_finalizes_each_case(tmp_path: Path, monkeypatch) -> None:
    ledger = Ledger.create_inherited(tmp_path / "ledger.json", {"attempts": []})
    ledger.save()
    gate = tmp_path / "gate.json"
    gate.write_text("{}", encoding="utf-8")
    import hashlib
    samples = []
    for case_id in ("02", "06", "07"):
        photo = tmp_path / f"{case_id}.jpg"
        photo.write_bytes(b"stub")
        samples.append({"id": case_id, "photos": [str(photo)],
                        "sha256": hashlib.sha256(photo.read_bytes()).hexdigest(), "request": {}})
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"samples": samples}), encoding="utf-8")
    monkeypatch.setattr(
        "line_drawing_eval.live.verify",
        lambda *a, **k: {"gate": str(gate), "origin": "http://127.0.0.1:9",
                         "source_fingerprint": {}, "health": {}},
    )
    monkeypatch.setattr(
        "line_drawing_eval.live.analyze_case",
        lambda client, case, target: {
            "case_id": case["id"], "success": True, "seconds": 1.0,
            "internal_cloud_request_starts_total": 4, "observation_protocol_repairs": 0,
        },
    )
    result = run_batch(
        gate_path=gate, ledger_path=tmp_path / "ledger.json", manifest_path=manifest,
        out_root=tmp_path / "out", run_name="e2-test",
        case_ids=["06", "07", "02"], client_factory=lambda origin: _FakeClient([]),
    )
    assert result["remaining_gateway_posts"] == 0
    stored = Ledger.load(tmp_path / "ledger.json")
    assert stored.data["budget"]["used_gateway_posts"] == 8
    assert stored.data["internal_request_starts"]["used"] == 34
    assert [item["status"] for item in stored.data["reservations"]] == ["complete"] * 3


def test_preflight_refuses_incomplete_gate(tmp_path: Path) -> None:
    ledger = Ledger.create_inherited(tmp_path / "ledger.json", {"attempts": []})
    ledger.save()
    gate = tmp_path / "gate.json"
    gate.write_text("{}", encoding="utf-8")
    with pytest.raises(PreflightError, match="missing fields"):
        verify(gate, tmp_path / "ledger.json")


def test_source_fingerprint_covers_tracked_source() -> None:
    fingerprint = source_fingerprint(ROOT)
    assert len(fingerprint["source_tree_sha256"]) == 64
    assert fingerprint["git_sha"]
    assert "src/camera_assistant/pipeline.py" in fingerprint["source_files"]
