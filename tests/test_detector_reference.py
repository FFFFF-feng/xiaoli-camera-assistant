import copy

import pytest
from test_detector_evaluation import experiment

from vision_lab_tool.detector_models import DetectorReference, GroundTruth


def draft():
    return DetectorReference(objects=[
        GroundTruth(gt_id="cup", label="cup", bbox=[.1, .1, .8, .9],
                    annotation_source="ai", target_level="whole"),
        GroundTruth(gt_id="inside", label="cup inside region", bbox=[.2, .2, .6, .4],
                    annotation_source="ai", target_level="region", parent_id="cup"),
    ])


def test_json_claims_cannot_confirm_ai_and_partial_confirmation_preserves_inventory():
    from vision_lab_tool.detector_reference import (
        apply_reference_edit,
        confirm_reference_objects,
        initialize_reference_workflow,
        reference_ready,
    )

    run = experiment()
    run.reference = draft()
    initialize_reference_workflow(run)
    ai_original = copy.deepcopy(run.provenance["reference_workflow"]["ai_draft"])
    forged = draft()
    for obj in forged.objects:
        obj.confirmed = True
        obj.annotation_source = "human"
    forged.complete = True
    apply_reference_edit(run, forged)
    assert not run.reference.complete and not any(o.confirmed for o in run.reference.objects)
    assert all(o.annotation_source == "ai" for o in run.reference.objects)
    confirm_reference_objects(run, ["cup"], "杯子整体和边界确认，内部区域待定", "复核预标注")
    assert run.reference.objects[0].confirmed and not run.reference.objects[1].confirmed
    assert not reference_ready(run)
    log = run.provenance["reference_workflow"]["confirmation_log"][0]
    assert log["user_text"] == "杯子整体和边界确认，内部区域待定"
    assert log["revision_reason"] == "复核预标注" and log["image_sha256"] == "image-hash"
    assert log["gt_id"] == "cup" and "bbox" in log["fields"] and log["confirmed_at"]
    assert run.reference.objects[0].annotation_source == "ai_reviewed_by_human"
    assert run.provenance["reference_workflow"]["ai_draft"] == ai_original
    deleted = run.reference.model_copy(deep=True)
    deleted.objects = deleted.objects[:1]
    with pytest.raises(ValueError, match="库存"):
        apply_reference_edit(run, deleted)
    changed_scope = run.reference.model_copy(deep=True)
    changed_scope.objects[1].required = False
    with pytest.raises(ValueError, match="必需"):
        apply_reference_edit(run, changed_scope)


def test_boundary_edit_revokes_previous_confirmation_until_explicit_new_review():
    from vision_lab_tool.detector_reference import (
        apply_reference_edit,
        confirm_reference_objects,
        initialize_reference_workflow,
    )

    run = experiment()
    run.reference = draft()
    initialize_reference_workflow(run)
    confirm_reference_objects(run, ["cup"], "杯子与边界已核对", "首次复核")
    changed = run.reference.model_copy(deep=True)
    changed.objects[0].bbox = [.05, .1, .8, .9]
    apply_reference_edit(run, changed)
    assert not run.reference.objects[0].confirmed
    with pytest.raises(ValueError, match="原文"):
        confirm_reference_objects(run, ["cup"], "", "修边界")
