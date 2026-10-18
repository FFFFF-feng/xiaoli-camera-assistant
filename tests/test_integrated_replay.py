"""Offline evidence tool tests; model/native extraction is a frozen test double."""
from __future__ import annotations

import base64
import copy
import hashlib
import importlib
import json
import socket
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from camera_assistant.composition_models import ObservedScene
from camera_assistant.services.image_analyzer import ImageAnalyzer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def tool():
    assert (ROOT / "scripts/replay_integrated_segmentation.py").is_file(), "replay tool missing"
    return importlib.import_module("replay_integrated_segmentation")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline replay attempted a network/model request")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr("camera_assistant.services.cloud.request_json", forbidden)


@pytest.fixture
def frozen_inputs(tmp_path):
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (80, 60), (120, 80, 40)).save(photo)
    photo_sha = hashlib.sha256(photo.read_bytes()).hexdigest()
    inspection = ImageAnalyzer().analyze(photo.read_bytes())
    raw = base64.b64decode(inspection.model_image_data_url.split(",", 1)[1])
    model_sha = hashlib.sha256(raw).hexdigest()
    metadata = {
        "reference_photo_id": "photo1", "scene_mode": "objects",
        "objects": [{
            "object_id": "object1", "label": "杯子冻结错类", "kind": "building",
            "role": "main", "depth": 1, "bbox": [.2, .2, .8, .8],
            "outline": [[0, 0], [1, 0], [1, 1], [0, 1]],
            "identity_features": ["原图可见边缘"], "evidence_photo_ids": ["photo1"],
        }], "limitations": ["这是冻结元数据"],
    }
    proposal = {
        "action_type": "crop", "goal": "历史取景", "actions": ["保持视角"],
        "reasons": ["历史理由"], "tradeoffs": ["局限"], "conditions": ["现场核对"],
        "limitations": ["历史版本"], "composition_intent": {
            "focus_object_id": "object1", "diagnosis": "冻结历史意图",
            "placement": "center", "vertical_placement": "keep",
            "subject_scale": "keep", "aspect": "keep",
        }, "storyboard": {"layers": []},
    }
    evidence = tmp_path / "evidence"
    for case in ("02", "06", "07", "08"):
        run = "live-run-2-diagnostic" if case == "07" else "live-run-1"
        folder = evidence / run / case
        write_json(folder / "observation-replay.json", {
            "model_image_sha256": model_sha, "metadata": metadata,
        })
        write_json(folder / "result.json", {"result": {"composition": {
            "proposals": [proposal],
        }}})
        write_json(folder.parent / "run_manifest.json", {"source_fingerprint": {
            "git_sha": "historical-dirty", "source_tree_sha256": "e" * 64,
        }})
    write_json(evidence / "live-run-1/07/observation-replay.json", {"wrong_source": True})
    manifest = tmp_path / "manifest.json"
    write_json(manifest, {"samples": [{
        "id": case, "title": f"case-{case}", "photos": [str(photo)], "sha256": photo_sha,
    } for case in ("02", "06", "07", "08")]})
    return evidence, manifest, metadata, model_sha


def install_offline_trace(replay, monkeypatch, tmp_path, captured, *, export=True):
    from camera_assistant.services import segmentation_provider
    from camera_assistant.services.composition_trace import stage_result
    segmentation_provider.close_providers()
    monkeypatch.setattr(segmentation_provider, "_EVIDENCE_ROOT", tmp_path / "provider")
    monkeypatch.setattr(replay, "source_fingerprint", lambda root: {
        "git_sha": "a" * 40, "source_tree_sha256": "b" * 64,
        "tracked_diff_sha256": "c" * 64, "source_files": {},
    })
    monkeypatch.setattr(replay, "dirty_files", lambda root: [])
    monkeypatch.setattr(replay, "git_branch", lambda root: "codex/offline-test")

    def trace(answer, inspection):
        captured.append(copy.deepcopy(answer))
        scene = ObservedScene.model_validate({**answer, "processing": [{
            "object_id": "object1", "requested_backend": "grabcut",
            "actual_backend": "grabcut", "mask_backend": "grabcut",
            "code": "contours_extracted",
        }]})
        provider = segmentation_provider.get_provider()
        provider.record_actual("grabcut")
        stage_result("contours", "complete", "contours_extracted",
                     object_id="object1", segmentation=scene.processing[0])
        if export:
            raw = base64.b64decode(inspection.model_image_data_url.split(",", 1)[1])
            provider.export_evidence(hashlib.sha256(raw).hexdigest(), {
                "object1": np.ones((60, 80), dtype=np.bool_),
            }, scene.objects, [row.model_dump() for row in scene.processing])
        return scene

    monkeypatch.setattr(replay, "trace_observed_scene", trace)


def test_offline_replay_keeps_metadata_and_links_masks_to_real_local_layout(
    frozen_inputs, tmp_path, monkeypatch,
):
    replay = tool()
    captured = []
    install_offline_trace(replay, monkeypatch, tmp_path, captured)
    evidence, manifest, metadata, model_sha = frozen_inputs
    out = tmp_path / "out"
    report = replay.run_replay(evidence_root=evidence, manifest_path=manifest, out=out)
    assert len(captured) == 4 and all(value == metadata for value in captured)
    assert report["cloud_requests"] == 0
    assert report["case_count"] == 4 and report["output_count"] == 4
    assert report["quality_passed"] is None
    assert report["cases"][2]["sources"]["observation"]["path"].endswith(
        "live-run-2-diagnostic\\07\\observation-replay.json"
    )
    record = json.loads((out / "06/record.json").read_text(encoding="utf-8"))
    assert record["model_image_sha256"] == model_sha
    assert record["intent_source"] == "historical_composition_intent"
    assert record["mask_evidence_available"] is True
    association = json.loads((out / "06/provider-evidence.json").read_text(encoding="utf-8"))
    assert association["records"][0]["input_sha256"] == model_sha
    assert (out / "06" / association["records"][0]["local_manifest"]).is_file()
    board = json.loads((out / "06/board.json").read_text(encoding="utf-8"))
    assert board["layout_engine"] == "local_v1"
    assert board["layers"][0]["kind"] == "building"
    assert board["layers"][0]["source_bbox"] == [.2, .2, .8, .8]
    gallery = (out / "gallery.html").read_text(encoding="utf-8").lower()
    assert "<script" not in gallery and "<form" not in gallery
    assert 'src="http' not in gallery and 'href="http' not in gallery
    assert "冻结" in gallery and "历史" in gallery and "当前离线" in gallery
    assert (out / "06/board.svg").read_text(encoding="utf-8").startswith("<svg")


@pytest.mark.parametrize(("mismatch", "expected"), [
    ("photo", "original_sha256_mismatch"), ("model", "model_image_sha256_mismatch"),
])
def test_hash_mismatch_is_recorded_and_does_not_drop_next_case(
    frozen_inputs, tmp_path, monkeypatch, mismatch, expected,
):
    replay = tool()
    captured = []
    install_offline_trace(replay, monkeypatch, tmp_path, captured)
    evidence, manifest, *_ = frozen_inputs
    path = manifest if mismatch == "photo" else evidence / "live-run-1/02/observation-replay.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if mismatch == "photo":
        value["samples"][0]["sha256"] = "0" * 64
    else:
        value["model_image_sha256"] = "0" * 64
    write_json(path, value)
    out = tmp_path / "out"
    report = replay.run_replay(evidence_root=evidence, manifest_path=manifest, out=out, cases=("02", "06"))
    assert report["case_count"] == 2 and report["output_count"] == 1
    assert report["cases"][0]["failure_code"] == expected
    assert json.loads((out / "02/record.json").read_text())["failure_code"] == expected
    assert report["cases"][1]["status"] == "output_created"
    assert len(captured) == 1


def test_missing_historical_intent_is_explicit_local_keep(frozen_inputs, tmp_path, monkeypatch):
    replay = tool()
    install_offline_trace(replay, monkeypatch, tmp_path, [])
    evidence, manifest, *_ = frozen_inputs
    write_json(evidence / "live-run-1/02/result.json", {"result": {"composition": {"proposals": []}}})
    report = replay.run_replay(evidence_root=evidence, manifest_path=manifest,
                               out=tmp_path / "out", cases=("02",))
    row = report["cases"][0]
    assert row["intent_source"] == "locally_fixed_keep_intent"
    intent = json.loads((tmp_path / "out/02/intent.json").read_text())
    assert [intent[key] for key in (
        "placement", "vertical_placement", "subject_scale", "aspect",
    )] == ["keep", "keep", "keep", "keep"]
    assert row["semantic_acceptance"] == "not_evaluated_frozen_metadata"


def test_no_mask_export_is_not_silently_accepted_as_mask_quality(
    frozen_inputs, tmp_path, monkeypatch,
):
    replay = tool()
    install_offline_trace(replay, monkeypatch, tmp_path, [], export=False)
    evidence, manifest, *_ = frozen_inputs
    row = replay.run_replay(evidence_root=evidence, manifest_path=manifest,
                            out=tmp_path / "out", cases=("02",))["cases"][0]
    assert row["status"] == "output_created"
    assert row["mask_evidence_available"] is False
    assert row["quality_passed"] is None


def test_existing_output_is_never_overwritten(frozen_inputs, tmp_path):
    replay = tool()
    evidence, manifest, *_ = frozen_inputs
    out = tmp_path / "out"
    out.mkdir()
    marker = out / "keep.txt"
    marker.write_text("keep")
    with pytest.raises(FileExistsError):
        replay.run_replay(evidence_root=evidence, manifest_path=manifest, out=out)
    assert marker.read_text() == "keep"


@pytest.mark.parametrize("aspect,height", [("landscape", 750), ("portrait", 1000/.75), ("square", 1000)])
def test_svg_preserves_the_boards_physical_frame_aspect(aspect, height):
    import xml.etree.ElementTree as ET

    svg = ET.fromstring(tool()._standalone_svg({"aspect": aspect, "layers": []}))
    view = list(map(float, svg.attrib["viewBox"].split()))
    assert view == pytest.approx([0, 0, 1000, height])
    transform = svg.find("{http://www.w3.org/2000/svg}g").attrib["transform"]
    assert list(map(float, transform.removeprefix("scale(").removesuffix(")").split())) == pytest.approx([1000, height])
