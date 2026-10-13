"""Human review provenance carried in detector-1 metadata, without changing old files."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from vision_lab_tool.detector_models import DetectorReference

WORKFLOW_VERSION = "human-reference-workflow-v1"


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def object_digest(obj):
    return _digest(obj.model_dump(mode="json", exclude={"confirmed", "annotation_source"}))


def initialize_reference_workflow(run):
    """Capture an immutable AI draft and the entire task inventory on first editing."""
    if "reference_workflow" not in run.provenance:
        run.provenance["reference_workflow"] = {
            "version": WORKFLOW_VERSION,
            "reference_id": _digest({
                "source_run_id": run.run_id, "reference": run.reference.model_dump(mode="json"),
            })[:32], "reference_version": 1,
            "parent_reference_id": None, "evaluation_scope": "original_complete_task",
            "image_sha256": run.image.get("original_sha256"),
            "inventory_gt_ids": [o.gt_id for o in run.reference.objects],
            "required_gt_ids": [o.gt_id for o in run.reference.objects if o.required],
            "ai_draft": run.reference.model_dump(mode="json"),
            "legacy_confirmed_objects": {
                o.gt_id: object_digest(o) for o in run.reference.objects
                if o.confirmed and o.annotation_source in {"human", "ai_reviewed_by_human"}
            },
            "confirmation_log": [], "pairing_confirmations": {},
            "ai_additions": [],
        }
    return run.provenance["reference_workflow"]


def _advance(workflow, *, invalidate_pairing=True):
    workflow["parent_reference_id"] = workflow["reference_id"]
    workflow["reference_id"] = uuid4().hex
    workflow["reference_version"] += 1
    # Correspondence belongs to one exact frozen reference, never another version.
    if invalidate_pairing:
        workflow["pairing_confirmations"] = {}


def validate_reference_inventory(run, reference=None):
    reference = reference or run.reference
    workflow = run.provenance.get("reference_workflow")
    if not workflow:
        return
    objects = {o.gt_id: o for o in reference.objects}
    if not set(workflow.get("inventory_gt_ids", [])).issubset(objects):
        raise ValueError("原任务参考库存不可删除；较小诊断需建立独立 evaluation_scope")
    for gt_id in workflow.get("required_gt_ids", []):
        if gt_id not in objects or not objects[gt_id].required or objects[gt_id].out_of_scope:
            raise ValueError("原任务必需单元不可移出范围；较小诊断需建立独立 evaluation_scope")


def _object_confirmed(workflow, obj):
    digest = object_digest(obj)
    if workflow.get("legacy_confirmed_objects", {}).get(obj.gt_id) == digest:
        return True
    return any(
        item.get("gt_id") == obj.gt_id and item.get("object_sha256") == digest
        and item.get("user_text", "").strip() and item.get("revision_reason", "").strip()
        and item.get("image_sha256") == workflow.get("image_sha256")
        for item in workflow.get("confirmation_log", [])
    )


def reference_ready(run):
    reference = run.reference
    if not reference.complete or not reference.objects or not all(
        o.confirmed for o in reference.objects
    ):
        return False
    workflow = run.provenance.get("reference_workflow")
    if not workflow:
        # Keep old human histories compatible; an AI flag alone is never human evidence.
        return all(o.annotation_source in {"human", "ai_reviewed_by_human"}
                   for o in reference.objects)
    try:
        validate_reference_inventory(run)
    except ValueError:
        return False
    return workflow.get("image_sha256") == run.image.get("original_sha256") and all(
        _object_confirmed(workflow, o) for o in reference.objects
    )


def apply_reference_edit(run, proposed: DetectorReference):
    """Importing JSON or editing a table changes a draft, never grants confirmation."""
    workflow = initialize_reference_workflow(run)
    validate_reference_inventory(run, proposed)
    if not workflow["inventory_gt_ids"] and not workflow["ai_draft"]["objects"]:
        workflow["ai_draft"] = proposed.model_dump(mode="json")
    original = {o["gt_id"]: o for o in (
        workflow["ai_draft"]["objects"] + workflow.get("ai_additions", [])
    )}
    for obj in proposed.objects:
        if obj.gt_id not in original and obj.annotation_source.startswith("ai"):
            captured = obj.model_dump(mode="json")
            workflow.setdefault("ai_additions", []).append(captured)
            original[obj.gt_id] = captured
    previous = {o.gt_id: o for o in run.reference.objects}
    updated = proposed.model_copy(deep=True)
    for obj in updated.objects:
        old = previous.get(obj.gt_id)
        obj.confirmed = bool(
            old and old.confirmed and object_digest(old) == object_digest(obj)
            and _object_confirmed(workflow, obj)
        )
        if obj.gt_id in original and original[obj.gt_id]["annotation_source"].startswith("ai"):
            obj.annotation_source = "ai_reviewed_by_human" if obj.confirmed else "ai"
        elif old:
            obj.annotation_source = old.annotation_source
        else:
            obj.annotation_source = "human_draft"
    updated.complete = bool(updated.complete and updated.objects and all(
        o.confirmed for o in updated.objects
    ))
    if updated.model_dump() != run.reference.model_dump():
        _advance(workflow, invalidate_pairing=updated.objects != run.reference.objects)
    workflow["inventory_gt_ids"] = sorted(set(workflow["inventory_gt_ids"]) | {
        o.gt_id for o in updated.objects
    })
    workflow["required_gt_ids"] = sorted(set(workflow["required_gt_ids"]) | {
        o.gt_id for o in updated.objects if o.required
    })
    run.reference = updated
    return updated


def confirm_reference_objects(run, gt_ids, user_text, revision_reason):
    if not gt_ids:
        raise ValueError("请选择明确确认的参考 ID")
    if not user_text.strip() or not revision_reason.strip():
        raise ValueError("人工确认须填写用户原文与修订理由")
    workflow = initialize_reference_workflow(run)
    validate_reference_inventory(run)
    objects = {o.gt_id: o for o in run.reference.objects}
    if not set(gt_ids).issubset(objects):
        raise ValueError("确认 ID 不在参考库存中")
    _advance(workflow)
    for gt_id in dict.fromkeys(gt_ids):
        obj = objects[gt_id]
        original = next((o for o in (
            workflow["ai_draft"]["objects"] + workflow.get("ai_additions", [])
        ) if o["gt_id"] == gt_id), {})
        obj.annotation_source = (
            "ai_reviewed_by_human"
            if original.get("annotation_source", "").startswith("ai") else "human"
        )
        obj.confirmed = True
        workflow["confirmation_log"].append({
            "gt_id": gt_id, "fields": sorted(type(obj).model_fields),
            "user_text": user_text, "confirmed_at": datetime.now(UTC).isoformat(),
            "revision_reason": revision_reason, "image_sha256": workflow["image_sha256"],
            "sample_id": run.provenance.get("sample_id"),
            "reference_id": workflow["reference_id"],
            "object_sha256": object_digest(obj), "source": obj.annotation_source,
            "values": obj.model_dump(mode="json"),
        })
    return run.reference


def _pairing_digest(run, review):
    return _digest({
        "reference_objects": {
            obj.gt_id: object_digest(obj) for obj in run.reference.objects
        },
        "matches": review.box_matches, "ignored": review.ignored_pred_ids,
        "in_scope": review.in_scope_pred_ids,
    })


def confirm_pairing(run, result, review, user_text, revision_reason):
    if not user_text.strip() or not revision_reason.strip():
        raise ValueError("配对确认须填写用户原文与修订理由")
    if not reference_ready(run):
        raise ValueError("请先完成原任务全部参考确认")
    from vision_lab_tool.detector_evaluation import validate_review

    validate_review(run, result, review)
    workflow = initialize_reference_workflow(run)
    workflow["pairing_confirmations"][result.result_id] = {
        "pairing_sha256": _pairing_digest(run, review), "user_text": user_text,
        "revision_reason": revision_reason, "confirmed_at": datetime.now(UTC).isoformat(),
        "image_sha256": run.image.get("original_sha256"),
        "reference_id": workflow["reference_id"], "box_matches": dict(review.box_matches),
    }


def pairing_ready(run, result, review):
    workflow = run.provenance.get("reference_workflow")
    if not workflow:
        return True
    confirmation = workflow.get("pairing_confirmations", {}).get(result.result_id, {})
    return bool(
        confirmation.get("user_text", "").strip()
        and confirmation.get("revision_reason", "").strip()
        and confirmation.get("pairing_sha256") == _pairing_digest(run, review)
    )
