"""Offline fixtures. Every fixture result is explicitly simulated."""
from vision_lab_tool.detector_models import DetectionObject, DetectionResult


def detect_mock(image, queries, config, case="valid"):
    labels = queries or ["person"]
    raw = []
    if case != "empty":
        raw.append({"object_id": "mock-1", "label": labels[0], "bbox": [.1, .1, .7, .8],
                    "score": .8})
    if case in {"ambiguous", "duplicate_id", "overlap"}:
        raw.append({"object_id": "mock-1" if case == "duplicate_id" else "mock-2",
                    "label": "hand" if case == "overlap" else labels[0],
                    "bbox": [.2, .2, .4, .4] if case == "overlap" else [.72, .1, .95, .8],
                    "score": .7})
    if case == "invalid_box":
        raw[0]["bbox"] = [.8, .1, .2, .7]
    if case == "unsupported":
        raw[0]["label"] = "person" if config.detector == "yolo26" else labels[0]
    objects = []
    errors = []
    for item in raw:
        try:
            if item["object_id"] in {v.object_id for v in objects}:
                raise ValueError("duplicate ID")
            objects.append(DetectionObject(
                object_id=item["object_id"], label_original=item["label"],
                label_display=item["label"], score=item["score"],
                bbox_native=item["bbox"], bbox_postprocessed=item["bbox"], bbox=item["bbox"],
                coordinate_basis="simulated normalized xyxy on sent JPEG",
                target_level="part" if item["label"] == "hand" else "instance",
            ))
        except ValueError as exc:
            errors.append(str(exc))
    status = "schema_error" if errors else "success" if objects else "empty"
    return DetectionResult(config=config, status=status, raw_candidates=raw,
                           candidates=objects, filtered_candidates=objects,
                           diagnostics=errors, real=False, timings={"total": .001},
                           metadata={"simulated": True, "fixture": case,
                                     "source_image_size": image.sent_size})


def vlm_payload(case="valid"):
    query = "instrument" if case == "unsupported" else "person"
    obj = {"object_id": "v1", "label": query, "query": query,
           "bbox": [.1, .1, .7, .8], "confidence": .9,
           "target_level": "instance", "entity_kind": "unknown", "parent_object_id": None}
    if case == "vlm_invalid_box":
        obj["bbox"] = [0, 0, 1000, 1000]
    if case == "vlm_semantic":
        obj["query"] = None
    return {"objects": [obj], "main_subject_ids": ["v1"], "subject_status": "selected"}
