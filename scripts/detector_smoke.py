"""Offline local integration smoke. No VLM, no ground truth, no accuracy claims."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import ImageDraw

from vision_lab_tool.detector_models import DetectorConfig
from vision_lab_tool.detectors.client import DetectorClient
from vision_lab_tool.images import prepare_image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path,
                        default=ROOT / "data/vision_lab/test_sets/contrast_10_v1/images/P02.jpg")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "data/vision_lab/detector_experiments/smoke_cpu")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    image = prepare_image(args.image.read_bytes())
    (args.output / "sent.jpg").write_bytes(image.sent_bytes)
    image.corrected.save(args.output / "corrected.jpg")
    client = DetectorClient()
    results = []
    try:
        for name in ("grounding_dino", "yolo26"):
            config = DetectorConfig(detector=name, device=args.device, timeout_seconds=args.timeout)
            for run in ("cold", "hot"):
                # Generic fixed smoke queries; no manifest/truth/title query extraction.
                result = client.detect(image, ["person", "bicycle", "dog", "car"], config)
                (args.output / f"{name}_{run}.json").write_text(
                    result.model_dump_json(indent=2), encoding="utf-8")
                overlay = image.corrected.copy()
                draw = ImageDraw.Draw(overlay)
                for obj in result.filtered_candidates:
                    box = [obj.bbox[i] * (overlay.width if i % 2 == 0 else overlay.height)
                           for i in range(4)]
                    draw.rectangle(box, outline="#f57b42", width=3)
                    draw.text((box[0], box[1]), obj.label_original, fill="#f57b42")
                overlay.save(args.output / f"{name}_{run}_overlay.jpg")
                summary = {"detector": name, "run": run, "status": result.status,
                           "candidate_count": len(result.candidates),
                           "raw_count": len(result.raw_candidates), "timings": result.timings,
                           "diagnostics": result.diagnostics, "real": result.real,
                           "model_revision": result.metadata.get("model_revision"),
                           "input_size": result.metadata.get("actual_input_size")}
                results.append(summary)
                print(json.dumps(summary, ensure_ascii=True), flush=True)
    finally:
        client.stop_worker()
    report = {"created_at": datetime.now(UTC).isoformat(), "image": str(args.image),
              "image_metadata": image.metadata(), "results": results,
              "vlm_calls": 0, "network_in_worker": "disabled",
              "quality_evaluated": False, "scope": "integration smoke only; no human ground truth"}
    (args.output / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if all(item["status"] in ("success", "partial_coordinates") and
                    item["candidate_count"] > 0 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
