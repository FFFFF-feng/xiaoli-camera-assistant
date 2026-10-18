"""Reconstruct saved E2 geometry for offline comparison; never an E2 input replay.

Original recognition bboxes/masks were not recorded. This tool preserves that
gap, verifies original photo/result hashes, and separates historical ROI tests.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import importlib.util
import io
import json
import shutil
import socket
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from camera_assistant.composition_models import CompositionAdvice, CompositionIntent, ObservedScene
from camera_assistant.config import Settings
from camera_assistant.services import segmentation_provider
from camera_assistant.services.image_analyzer import ImageAnalyzer
from camera_assistant.services.layout_solver import solve_layout
from camera_assistant.services.observation_evidence import category_adaptation, observation_summary
from camera_assistant.services.observed_composition import prepare_observation
from camera_assistant.services.photo_boundary import boundary_evidence, split_frame_edges
from camera_assistant.services.pixel_contours import trace_observed_scene
from camera_assistant.services.pixel_small_objects import hole_matches_exterior
from camera_assistant.services.segmentation_provider import use_segmentation
from line_drawing_eval.preflight import dirty_files, source_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def source_scene(board):
    """Recover post-segmentation geometry, not the original observation ROI."""
    objects = []
    for layer in board["layers"]:
        obj = {**layer, "object_id": layer["source_object_id"], "bbox": layer["source_bbox"], "parts": []}
        if layer.get("representation") in {"context_lines", "scene_structure"}:
            if not layer.get("source_details"):
                raise ValueError("saved_source_details_missing")
            obj["details"] = layer["source_details"]
        objects.append(obj)
    return ObservedScene.model_validate({"scene_mode": "continuous" if any(
        o.get("representation") == "scene_structure" for o in objects) else "objects",
        "objects": objects, "limitations": ["离线重建的分割后几何；原始识别框与mask未留存。"]})


def candidate_scene(scene, rgb, work_size):
    data = scene.model_dump()
    changes = []
    for obj in data["objects"]:
        adaptation = category_adaptation(obj)
        if adaptation:
            obj.update(kind=adaptation["normalized_kind"], category_adaptation=adaptation)
        if obj["representation"] != "silhouette":
            continue
        # These are stored outline samples with a known baseline pixel convention.
        # It is deliberately not labelled a recovered E2 raw mask.
        width, height = (rgb.shape[1], rgb.shape[0]) if obj["kind"] in {"pet", "dog", "cat"} else work_size
        obj["photo_boundary"] = boundary_evidence(obj["outline"], obj["bbox"], width, height, basis="saved_outline_v1")
        if obj["photo_boundary"]["clipped_edges"]:
            obj["details"] = split_frame_edges(obj["details"], obj["bbox"], width, height,
                                                obj["photo_boundary"]["clipped_edges"])
        if obj["kind"] in {"pet", "dog", "cat"} and obj["holes"]:
            x1, y1, x2, y2 = obj["bbox"]
            def pixels(path):
                return np.array([[round((x1+x*(x2-x1))*rgb.shape[1]),
                                  round((y1+y*(y2-y1))*rgb.shape[0])] for x, y in path], np.int32).reshape(-1, 1, 2)
            selected = np.zeros(rgb.shape[:2], np.uint8)
            cv2.drawContours(selected, [pixels(obj["outline"])], -1, 255, cv2.FILLED)
            retained = []
            for index, hole in enumerate(obj["holes"]):
                keep = hole_matches_exterior(rgb, selected, pixels(hole))
                changes.append({"object_id": obj["object_id"], "hole_index": index, "transparent": keep,
                                "basis": "reconstructed_saved_polygon_and_actual_photo_colours_not_raw_mask"})
                if keep:
                    retained.append(hole)
                elif hole+[hole[0]] not in obj["details"]:
                    obj["details"] = [*obj["details"], hole+[hole[0]]][:96]
            obj["holes"] = retained
    return ObservedScene.model_validate(data), changes


def package_result(raw, board, framing, scene, provenance, *, bind_summary=True):
    value = copy.deepcopy(raw)
    result = value.get("result", value)
    advice = CompositionAdvice.model_validate(result["composition"])
    proposal = advice.proposals[0].model_copy(update={"storyboard": board, "framing_plan": framing})
    advice = advice.model_copy(update={"proposals": [proposal]})
    if bind_summary:
        advice = observation_summary(advice, scene)
    result["composition"] = advice.model_dump(mode="json")
    value["offline_replay"] = provenance
    return value


def run(e2_root, out, cases, baseline):
    out.mkdir(parents=True, exist_ok=False)
    baseline_code = subprocess.check_output(["git", "show", f"{baseline}:src/camera_assistant/services/layout_solver.py"], cwd=ROOT)
    code_path = out/"baseline_layout_solver.py"
    code_path.write_bytes(baseline_code)
    spec = importlib.util.spec_from_file_location("e2_baseline_layout", code_path)
    old_solver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old_solver)
    fingerprint = source_fingerprint(ROOT)
    report = {"scope": "offline_saved_geometry_reconstruction_not_new_cloud_acceptance",
        "baseline": baseline, "baseline_solver_sha256": hashlib.sha256(baseline_code).hexdigest(),
        "current": {k: v for k, v in fingerprint.items() if k != "source_files"}, "dirty_files": dirty_files(ROOT),
        "script_sha256": sha(Path(__file__)), "cloud_requests": 0, "cases": []}
    for case in cases:
        started = time.perf_counter()
        folder = out/case
        folder.mkdir()
        run_root = e2_root/f"e2-12bcccc-{case}"
        manifest = load(run_root/"run_manifest.json")
        sample = next(c for c in manifest["cases"] if c["id"] == case)
        photo = Path(sample["photo"])
        if sha(photo) != sample["sha256"]:
            raise ValueError("original_photo_sha256_mismatch")
        raw_path = run_root/case/"result.json"
        raw = load(raw_path)
        result = raw.get("result", raw)
        board = result["composition"]["proposals"][0]["storyboard"]
        source = source_scene(board)
        inspection = ImageAnalyzer(max_image_mb=100).analyze(photo.read_bytes())
        rgb_image = Image.open(io.BytesIO(base64.b64decode(inspection.model_image_data_url.split(',', 1)[1]))).convert('RGB')
        rgb = np.asarray(rgb_image)
        work = rgb_image.copy()
        work.thumbnail((720, 720))
        plan = CompositionIntent.model_validate(result["composition"]["proposals"][0]["composition_intent"])
        carrier = CompositionAdvice.model_validate(result["composition"]).proposals[0]
        aspect = inspection.metrics.width/inspection.metrics.height
        old_board, old_framing = old_solver.solve_layout(plan, source, aspect, carrier)
        old_main = next(l for l in old_board.layers if l.role == 'main')
        saved_main = next(l for l in board["layers"] if l["role"] == 'main')
        delta = max(abs(a-b) for a, b in zip(old_main.bbox, saved_main["bbox"], strict=True))
        candidate, hole_changes = candidate_scene(source, rgb, work.size)
        missing = [d for d in result["composition"]["diagnostics"] if (d.get("segmentation") or {}).get("actual_backend") == 'none']
        # Mapping is reconstructed only if the remaining whole-object identity is unique.
        drawn_labels = {l['label'] for l in board['layers']}
        remaining = [o for o in result['scene'].get('objects', []) if o.get('target_level') == 'whole'
                     and o.get('entity_kind') == 'physical' and o.get('label') not in drawn_labels]
        missing_inputs = []
        if len(missing) == len(remaining) == 1:
            candidate = ObservedScene.model_validate({**candidate.model_dump(), "unrendered_objects": [
                {"object_id": missing[0]['object_id'], "label": remaining[0]['label'],
                 "reason_code": missing[0]['segmentation']['code']}]})
            missing_inputs.append('missing-label mapping reconstructed from sole undrawn semantic object + failed contour ID')
        new_board, new_framing = solve_layout(plan, candidate, aspect, carrier)
        provenance = {"kind": "reconstructed_from_saved_post_segmentation_geometry", "new_cloud_request": False,
            "original_result": str(raw_path), "original_result_sha256": sha(raw_path), "original_photo_sha256": sha(photo),
            "inherited_E2_trace_id": result['composition'].get('trace_id'),
            "retained_E2_fields_not_new_measurements": ["scene", "recommendation", "timings", "request_id", "composition.trace_id"],
            "missing": ["E2 raw recognition bbox", "E2 raw observation response", "E2 raw binary mask", *missing_inputs]}
        shutil.copyfile(photo, folder/'original.jpg')
        shutil.copyfile(raw_path, folder/'e2-original.json')
        write(folder/'offline-baseline.json', package_result(raw, old_board, old_framing, source, provenance, bind_summary=False))
        write(folder/'candidate.json', package_result(raw, new_board, new_framing, candidate, provenance))
        write(folder/'reconstructed-source.json', candidate.model_dump(mode='json'))
        row = {"case": case, **provenance, "original_aspect": aspect, "baseline_work_size": work.size,
               "baseline_main_bbox_max_abs_error": delta, "source_bbox": saved_main['source_bbox'],
               "E2_target_bbox": saved_main['bbox'], "candidate_bbox": next(l.bbox for l in new_board.layers if l.role == 'main'),
               "category_adaptations": [o.category_adaptation.model_dump() for o in candidate.objects if o.category_adaptation],
               "photo_boundary": next((o.photo_boundary.model_dump() for o in candidate.objects if o.role == 'main' and o.photo_boundary), None),
               "hole_colour_reconstruction": hole_changes, "local_seconds": time.perf_counter()-started,
               "quality_pass_claimed": False}
        write(folder/'record.json', row)
        report['cases'].append(row)
    historical = ROOT/'.tmp/composition-replay/f40eb475727f40c8812c8ca19280d8d9.json'
    if historical.is_file() and '02' in cases:
        folder = out/'02-historical-roi'
        folder.mkdir()
        frozen = load(historical)
        sample = load(e2_root/'e2-12bcccc-02/run_manifest.json')['cases'][0]
        inspection = ImageAnalyzer().analyze(Path(sample['photo']).read_bytes())
        if hashlib.sha256(base64.b64decode(inspection.model_image_data_url.split(',', 1)[1])).hexdigest() != frozen['model_image_sha256']:
            raise ValueError('historical_model_image_sha256_mismatch')
        settings = Settings(demo_mode=True, api_key='', base_url='https://example.invalid', vision_model='', text_model='',
            timeout_seconds=120, max_image_mb=100, knowledge_dir=ROOT/'knowledge', segmentation_evidence=True)
        old_evidence_root = segmentation_provider._EVIDENCE_ROOT
        segmentation_provider._EVIDENCE_ROOT = folder/'pixel-evidence'
        try:
            tick = time.perf_counter()
            with use_segmentation(settings):
                scene = trace_observed_scene(prepare_observation(frozen['metadata']), inspection)
            raw = load(e2_root/'e2-12bcccc-02/02/result.json')
            result = raw.get('result', raw)
            carrier = CompositionAdvice.model_validate(result['composition']).proposals[0]
            board, framing = solve_layout(carrier.composition_intent, scene, inspection.metrics.width/inspection.metrics.height, carrier)
            provenance = {'kind': 'historical_20261017_recognition_ROI_independent_pixel_diagnostic_not_E2_input',
                'historical_input': str(historical), 'historical_input_sha256': sha(historical),
                'E2_ROI_recovered': False, 'cloud_requests': 0, 'local_seconds': time.perf_counter()-tick}
            write(folder/'candidate.json', package_result(raw, board, framing, scene, provenance))
            write(folder/'source.json', scene.model_dump(mode='json'))
            write(folder/'record.json', {**provenance, 'processing': [r.model_dump() for r in scene.processing]})
        finally:
            segmentation_provider._EVIDENCE_ROOT = old_evidence_root
            segmentation_provider.close_providers()
    write(out/'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--e2-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cases', default='06,07,02')
    parser.add_argument('--baseline', default='12bcccc18e42d47210245b5d195830c7ae5029c0')
    args = parser.parse_args()
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('offline_only_no_network')):
        report = run(args.e2_root.resolve(), args.out.resolve(), args.cases.split(','), args.baseline)
    print(json.dumps({'out': str(args.out), 'cases': len(report['cases']), 'cloud_requests': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
