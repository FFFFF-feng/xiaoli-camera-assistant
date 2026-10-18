"""Offline regression coverage for A's frozen-version acceptance gate."""

from __future__ import annotations

import hashlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from line_drawing_eval import live, preflight
from line_drawing_eval.ledger import Ledger
from line_drawing_eval.preflight import PreflightError


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def frozen_gate(tmp_path: Path, monkeypatch):
    root = tmp_path / "source"
    assets = root / "mobile" / "dist" / "assets"
    assets.mkdir(parents=True)
    (assets / "app.js").write_text("console.log('current build');", encoding="utf-8")
    (assets / "app.css").write_text("body{margin:0}", encoding="utf-8")
    index = assets.parent / "index.html"
    index.write_text(
        '<script type="module" src="/assets/app.js?v=1"></script>'
        '<link rel="stylesheet" href="./assets/app.css">', encoding="utf-8",
    )
    gate = {
        "status": "INTEGRATION_READY",
        "commit": "a" * 40,
        "branch": "codex/integrated",
        "source_root": str(root),
        "source_tree_sha256": "b" * 64,
        "dirty_files": [],
        "port": 8093,
        "pid": 123,
        "built_assets": {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (index, assets / "app.js", assets / "app.css")
        },
        "health": {"service": "xiaoli-mobile-api", "analysis_mode": "cloud"},
        "segmentation": {"backend": "grabcut", "device": "cpu"},
        "frozen_at": "2026-10-18T08:00:00+08:00",
    }
    health = {
        "service": "xiaoli-mobile-api", "analysis_mode": "cloud",
        "segmentation": {
            "configured_backend": "grabcut", "device": "cpu", "weights_sha256": None,
            "last_actual_backend": None, "last_weights_sha256": None,
            "inference_proven": False,
        },
    }
    gate_path = tmp_path / "gate.json"
    ledger_path = tmp_path / "ledger.json"
    Ledger.create_inherited(ledger_path, {"attempts": []}).save()

    def git_run(*args, **kwargs):
        assert kwargs.get("cwd") == root
        return "codex/integrated" if "--abbrev-ref" in args else gate["commit"]

    monkeypatch.setattr(preflight, "_run", git_run)
    monkeypatch.setattr(preflight, "source_fingerprint", lambda path: {
        "git_sha": "a" * 40, "tracked_diff_sha256": "c" * 64,
        "source_tree_sha256": "b" * 64, "source_files": {},
    })
    monkeypatch.setattr(preflight, "dirty_files", lambda path: [])
    monkeypatch.setattr(preflight, "listening_pid", lambda port: 123)
    monkeypatch.setattr(preflight, "process_command", lambda pid: f'python "{root}/entry.py"')
    monkeypatch.setattr(preflight, "health_snapshot", lambda origin: health)

    def verify_gate():
        _write_json(gate_path, gate)
        return preflight.verify(gate_path, ledger_path)

    return gate, health, verify_gate, gate_path, ledger_path


@pytest.mark.parametrize("field", ["health", "built_assets"])
def test_gate_rejects_empty_identity_or_asset_inventory(frozen_gate, field):
    gate, _, verify_gate, *_ = frozen_gate
    gate[field] = {}
    with pytest.raises(PreflightError):
        verify_gate()


@pytest.mark.parametrize("missing", [
    "mobile/dist/index.html", "mobile/dist/assets/app.js", "mobile/dist/assets/app.css",
])
def test_gate_rejects_missing_current_index_or_referenced_asset(frozen_gate, missing):
    gate, _, verify_gate, *_ = frozen_gate
    del gate["built_assets"][missing]
    with pytest.raises(PreflightError):
        verify_gate()


@pytest.mark.parametrize(("field", "value"), [
    ("commit", "abc"), ("commit", "z" * 40),
    ("frozen_at", "not-iso"), ("frozen_at", "2026-10-18"),
])
def test_gate_rejects_unverifiable_commit_or_freeze_time(frozen_gate, field, value):
    gate, _, verify_gate, *_ = frozen_gate
    gate[field] = value
    with pytest.raises(PreflightError):
        verify_gate()


def test_gate_detects_changed_asset_bytes(frozen_gate):
    gate, _, verify_gate, *_ = frozen_gate
    (Path(gate["source_root"]) / "mobile/dist/assets/app.js").write_bytes(b"old build")
    with pytest.raises(PreflightError):
        verify_gate()


def test_gate_reports_configuration_without_claiming_inference(frozen_gate):
    _, _, verify_gate, _, ledger_path = frozen_gate
    before = ledger_path.read_bytes()
    report = verify_gate()
    assert report["ok"] is True
    assert report["generated_model_requests"] == 0
    assert report["segmentation"]["inference_proven"] is False
    assert report["segmentation"]["last_actual_backend"] is None
    assert ledger_path.read_bytes() == before


@pytest.mark.parametrize(("field", "value"), [
    ("configured_backend", "mobile_sam"), ("device", "cuda"),
    ("weights_sha256", "d" * 64),
])
def test_gate_rejects_live_segmentation_configuration_mismatch(frozen_gate, field, value):
    _, health, verify_gate, *_ = frozen_gate
    health["segmentation"][field] = value
    with pytest.raises(PreflightError):
        verify_gate()


def test_gate_rejects_missing_live_segmentation_diagnostic(frozen_gate):
    _, health, verify_gate, *_ = frozen_gate
    del health["segmentation"]
    with pytest.raises(PreflightError):
        verify_gate()


def test_gate_requires_actual_backend_for_inference_proof(frozen_gate):
    _, health, verify_gate, *_ = frozen_gate
    health["segmentation"]["inference_proven"] = True
    with pytest.raises(PreflightError):
        verify_gate()


def test_mobile_sam_gate_checks_weights_and_preserves_fallback_evidence(frozen_gate, tmp_path):
    gate, health, verify_gate, *_ = frozen_gate
    weights = tmp_path / "weights.pt"
    weights.write_bytes(b"local synthetic weights")
    digest = hashlib.sha256(weights.read_bytes()).hexdigest()
    gate["segmentation"] = {
        "backend": "mobile_sam", "device": "cpu",
        "weights_path": str(weights), "weights_sha256": digest,
    }
    health["segmentation"].update({
        "configured_backend": "mobile_sam", "weights_sha256": digest,
        "last_actual_backend": "grabcut", "inference_proven": True,
    })
    report = verify_gate()
    assert report["segmentation"]["configured_backend"] == "mobile_sam"
    assert report["segmentation"]["last_actual_backend"] == "grabcut"
    assert report["segmentation"]["inference_proven"] is True
    weights.write_bytes(b"replaced weights")
    with pytest.raises(PreflightError):
        verify_gate()


class Response:
    def __init__(self, *, status=200, content_type="application/x-ndjson", lines=()):
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.lines = lines

    def raise_for_status(self):
        return None

    def json(self):
        return {"status": "ok"}

    def iter_lines(self):
        return iter(self.lines)


class OfflineClient:
    def __init__(self, response):
        self.response = response

    def get(self, path):
        assert path == "/health"
        return Response()

    def post(self, path):
        assert path == "/session"
        return Response()

    @contextmanager
    def stream(self, method, path, **kwargs):
        assert (method, path) == ("POST", "/api/v1/analyze")
        yield self.response


@pytest.mark.parametrize(("response", "failure_code"), [
    (Response(status=500), "http_non_200"),
    (Response(content_type="text/plain"), "stream_content_type_invalid"),
    (Response(lines=[json.dumps({"type": "error"})]), "analysis_error_event"),
])
def test_live_failure_reason_survives_missing_final_summary(tmp_path, response, failure_code):
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"synthetic")
    result = live.analyze_case(OfflineClient(response), {
        "id": "02", "photo": str(photo), "sha256": "fake", "request": {},
    }, tmp_path / "02")
    assert result["failure_code"] == failure_code
    assert json.loads((tmp_path / "02/summary.json").read_text())["failure_code"] == failure_code


def test_dry_run_reports_health_get_and_zero_model_requests(frozen_gate, tmp_path, capsys):
    _, _, verify_gate, gate_path, ledger_path = frozen_gate
    verify_gate()
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"synthetic photo")
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {"samples": [{
        "id": "06", "photos": [str(photo)],
        "sha256": hashlib.sha256(photo.read_bytes()).hexdigest(), "request": {},
    }]})
    before = ledger_path.read_bytes()
    out = tmp_path / "never-created"
    assert live.main([
        "--gate", str(gate_path), "--ledger", str(ledger_path),
        "--manifest", str(manifest), "--out", str(out),
        "--run-name", "dry-check", "--cases", "06",
    ]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["generated_model_requests"] == 0
    assert plan["health_get_requests"] == 1
    assert "network_calls" not in plan
    assert not out.exists()
    assert ledger_path.read_bytes() == before
