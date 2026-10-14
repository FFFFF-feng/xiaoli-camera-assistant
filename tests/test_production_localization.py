"""Offline production association: real photography requests, synthetic detector boxes."""
from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from camera_assistant.config import Settings
from camera_assistant.models import (
    ExifInfo,
    ImageInspection,
    ImageMetrics,
    SceneAnalysis,
    UserRequest,
)
from camera_assistant.services.localization import GroundingDinoLocalizer
from vision_lab_tool.detector_models import DetectionObject, DetectionResult, SemanticObject

CAT_TASK = "突出猫的双眼，完整保留耳朵和胡须，简化背景并留出视线空间"
WATERFALL_TASK = "用三脚架重拍瀑布，希望水流拉丝并保留树林层次，没有ND滤镜"
P01_FULL_TASK = "突出猫的双眼，完整保留耳朵和胡须，简化背景，给出重拍时可以执行的构图调整。"
P10_FULL_TASK = "用三脚架重新拍摄瀑布，希望水流拉丝并保留树林层次，目前没有ND减光镜，请说明曝光取舍。"


def semantic(object_id, query, level="whole", entity="physical", parent=None):
    return SemanticObject(object_id=object_id, label=query, query=query,
                          target_level=level, entity_kind=entity, parent_object_id=parent)


def candidate(object_id="det_cat", label="cat", level="instance", score=.7):
    box = [.15, .1, .85, .9]
    return DetectionObject(object_id=object_id, label_original=label, label_display=label,
                           bbox_native=box, bbox_postprocessed=box, bbox=box,
                           target_level=level, score=score,
                           coordinate_basis="synthetic_corrected_normalized_xyxy")


def scene(objects, main_ids=None, subject_status="selected"):
    return SceneAnalysis(
        scene_type="general_scene", subject="offline scene", environment="outdoor",
        lighting="available", brightness="medium", backlight=False,
        subject_motion="static", dynamic_range="medium", desired_effects=[], confidence=.8,
        objects=objects, main_subject_ids=(main_ids if main_ids is not None else
            [objects[0].object_id] if objects and subject_status == "selected" else []),
        subject_status=subject_status,
    )


class OfflineDetector:
    """Replace only external inference; record the bytes/queries at its boundary."""
    def __init__(self, objects, status="success"):
        self.objects = objects
        self.status = status
        self.calls = []

    def detect(self, image, queries, config):
        self.calls.append((image, queries, config))
        return DetectionResult(config=config, status=self.status,
            candidates=self.objects, filtered_candidates=self.objects, real=False)

    def stop_worker(self):
        pass


@pytest.fixture
def inspection():
    output = BytesIO()
    Image.new("RGB", (80, 60), (90, 110, 120)).save(output, format="JPEG")
    return ImageInspection(exif=ExifInfo(), metrics=ImageMetrics(
        width=80, height=60, mean_brightness=.4, contrast=.2, shadow_ratio=.1,
        highlight_ratio=.1, sharpness_score=4),
        model_image_data_url="data:image/jpeg;base64," + base64.b64encode(
            output.getvalue()).decode())


def localize(inspection, task, objects=None, boxes=None, main_ids=None,
             subject_status="selected", detector_status="success"):
    objects = [semantic("cat_1", "cat")] if objects is None else objects
    boxes = [candidate()] if boxes is None else boxes
    semantic_scene = scene(objects, main_ids, subject_status)
    client = OfflineDetector(boxes, detector_status)
    settings = Settings(demo_mode=False, api_key="", base_url="https://example.invalid/v1",
        vision_model="offline-vision", text_model="offline-advisor", timeout_seconds=5,
        max_image_mb=15, knowledge_dir=Path("knowledge"))
    result = GroundingDinoLocalizer(settings, client).localize(
        inspection, UserRequest(intent=task), semantic_scene)
    return result, client, semantic_scene


def test_cat_details_and_retention_allow_unique_whole_subject(inspection):
    result, _, semantic_scene = localize(inspection, CAT_TASK)
    assert result.selection.status == "selected"
    assert result.selection.selected_ids == ["det_cat"]
    assert result.queries["task_text"] == CAT_TASK
    assert result.queries["task_scope"]["missing_semantic_units"] == []
    assert result.candidates[0].entity_kind == "unknown"
    assert semantic_scene.objects[0].entity_kind == "physical"
    assert result.candidates[0].target_level == "instance"


def test_waterfall_production_vocabulary_and_tree_protection_are_separate(inspection):
    objects = [semantic("fall_1", "waterfall"), semantic("rock_1", "rock"),
               semantic("forest_1", "forest")]
    boxes = [candidate("det_fall", "waterfall"), candidate("det_tree", "tree"),
             candidate("det_forest", "forest")]
    result, client, _ = localize(inspection, WATERFALL_TASK, objects, boxes, ["fall_1"])
    assert result.selection.status == "selected"
    assert result.selection.selected_ids == ["det_fall"]
    assert "waterfall" in client.calls[0][1]
    assert result.queries["task_scope"]["required_units"][0]["query"] == "waterfall"
    assert all(unit["query"] != "forest" for unit in
               result.queries["task_scope"]["required_units"])


def test_p01_generic_composition_output_request_does_not_create_an_object(inspection):
    result, _, _ = localize(inspection, P01_FULL_TASK)
    assert result.selection.status == "selected"
    assert result.selection.selected_ids == ["det_cat"]
    assert result.queries["task_text"] == P01_FULL_TASK
    scope = result.queries["task_scope"]
    assert [unit["query"] for unit in scope["required_units"]] == ["cat"]
    assert scope["missing_semantic_units"] == []


def test_p10_reshoot_and_exposure_constraints_do_not_create_extra_objects(inspection):
    result, _, _ = localize(inspection, P10_FULL_TASK,
        [semantic("fall_1", "waterfall"), semantic("forest_1", "forest")],
        [candidate("det_fall", "waterfall"), candidate("det_forest", "forest")], ["fall_1"])
    assert result.selection.status == "selected"
    assert result.selection.selected_ids == ["det_fall"]
    assert result.queries["task_text"] == P10_FULL_TASK
    scope = result.queries["task_scope"]
    assert [unit["query"] for unit in scope["required_units"]] == ["waterfall"]
    assert scope["missing_semantic_units"] == []


@pytest.mark.parametrize("target_request", ["突出猫和未知物件", "定位猫的头部", "突出两只猫",
                                      "突出猫，给出重拍时猫和未知物件的构图调整"])
def test_composition_output_clause_cannot_hide_required_entities_parts_or_counts(inspection,
                                                                               target_request):
    task = target_request + "，给出重拍时可以执行的构图调整。"
    result, _, _ = localize(inspection, task)
    assert result.selection.status == "ambiguous"
    assert result.selection.selected_ids == []
    assert result.queries["task_scope"]["missing_semantic_units"]


def test_exact_sent_jpeg_and_digest_are_preserved(inspection):
    _, client, _ = localize(inspection, CAT_TASK)
    prepared = client.calls[0][0]
    sent = base64.b64decode(inspection.model_image_data_url.split(",", 1)[1])
    assert prepared.sent_bytes == sent
    assert prepared.corrected.size == (80, 60)
    assert prepared.corrected_sha256 == hashlib.sha256(sent).hexdigest()


def test_multiple_cat_candidates_do_not_use_score_to_force_subject(inspection):
    result, _, _ = localize(inspection, CAT_TASK,
        boxes=[candidate("first", score=.99), candidate("second", score=.36)])
    assert result.selection.status == "ambiguous"
    assert result.selection.selected_ids == []


@pytest.mark.parametrize("task", ["突出两只猫", "突出2只猫", "photograph two cats",
                                  "photograph cats", "突出所有猫"])
def test_plural_or_count_cannot_shrink_to_one_visible_cat(inspection, task):
    result, _, _ = localize(inspection, task)
    assert result.selection.status == "ambiguous"
    assert result.selection.selected_ids == []
    assert result.queries["task_scope"]["missing_semantic_units"]


@pytest.mark.parametrize("task", ["突出猫和另一件未知物件", "突出猫和螺丝",
                                  "突出螺丝和猫", "photograph cat and widget"])
def test_unknown_conjunction_goal_is_not_erased_by_main_subject(inspection, task):
    result, _, _ = localize(inspection, task)
    assert result.selection.status == "ambiguous"
    assert result.selection.selected_ids == []
    assert result.queries["task_text"] == task
    assert result.queries["task_scope"]["status"] == "unknown"


def test_known_second_goal_missing_from_vlm_blocks_complete_selection(inspection):
    result, _, _ = localize(inspection, "突出猫和狗")
    assert result.selection.status == "ambiguous"
    assert result.selection.selected_ids == []
    assert "task:dog" in result.queries["task_scope"]["missing_semantic_units"]


def test_explicit_multiple_main_subjects_are_all_preserved(inspection):
    result, _, _ = localize(inspection, "突出猫和狗",
        [semantic("cat_1", "cat"), semantic("dog_1", "dog")],
        [candidate(), candidate("det_dog", "dog")], ["cat_1", "dog_1"])
    assert result.selection.status == "selected"
    assert result.selection.selected_ids == ["det_cat", "det_dog"]


@pytest.mark.parametrize("semantic_level,box_level", [("part", "instance"),
                                                       ("whole", "part")])
def test_whole_and_part_geometry_cannot_replace_each_other(inspection,
                                                         semantic_level, box_level):
    result, _, _ = localize(inspection, "定位猫的头部",
        [semantic("cat_1", "cat", semantic_level)], [candidate(level=box_level)])
    assert result.selection.status != "selected"
    assert result.selection.selected_ids == []
    assert result.candidates[0].target_level == box_level


@pytest.mark.parametrize("label", ["cat head", "cat unknownthing", "cat dog"])
def test_complete_category_label_is_required_for_whole_cat(inspection, label):
    result, _, _ = localize(inspection, CAT_TASK, boxes=[candidate(label=label)])
    assert result.selection.status != "selected"
    assert result.selection.selected_ids == []


@pytest.mark.parametrize("entity", ["reflection", "depiction", "mannequin", "scale_model"])
def test_category_agreement_cannot_prove_special_entity_identity(inspection, entity):
    result, _, _ = localize(inspection, "突出猫", [semantic("cat_1", "cat", entity=entity)])
    assert result.selection.status != "selected"
    assert result.selection.selected_ids == []
    assert result.candidates[0].entity_kind == "unknown"


@pytest.mark.parametrize("task", ["突出猫的倒影", "突出镜子里的猫", "突出画中的猫",
                                  "photograph the reflection of cat"])
def test_task_identity_markers_cannot_be_proven_by_category_box(inspection, task):
    result, _, _ = localize(inspection, task)
    assert result.selection.status != "selected"
    assert result.selection.selected_ids == []


@pytest.mark.parametrize("status", ["timeout", "runtime_error", "partial_coordinates"])
def test_failed_or_partial_detector_never_selects_from_surviving_boxes(inspection, status):
    result, _, _ = localize(inspection, CAT_TASK, detector_status=status)
    assert result.selection.status == "abstained"
    assert result.selection.selected_ids == []
    assert result.candidates


@pytest.mark.parametrize("status", ["abstained", "ambiguous"])
def test_vlm_without_main_subject_retains_candidates_and_abstains(inspection, status):
    result, _, _ = localize(inspection, CAT_TASK, main_ids=[], subject_status=status)
    assert result.selection.status == status
    assert result.selection.selected_ids == []
    assert result.candidates


def test_empty_query_skips_external_inference(inspection):
    result, client, _ = localize(inspection, "请优化取景", [], [], [], "abstained")
    assert client.calls == []
    assert result.status == "query_missing"
    assert result.selection.status == "abstained"


def test_input_semantics_and_detector_boxes_are_immutable(inspection):
    objects, boxes = [semantic("cat_1", "cat")], [candidate()]
    semantic_before, box_before = objects[0].model_dump(), boxes[0].model_dump()
    result, _, _ = localize(inspection, CAT_TASK, objects, boxes)
    assert objects[0].model_dump() == semantic_before
    assert boxes[0].model_dump() == box_before
    assert result.candidates[0].bbox == [.15, .1, .85, .9]


def test_unresolved_geometry_level_cannot_supply_unique_subject(inspection):
    result, _, _ = localize(inspection, "突出猫",
        [semantic("cat_1", "cat", "unknown")], [candidate(level="unknown")])
    assert result.selection.status == "ambiguous"
    assert result.selection.selected_ids == []


def test_other_subject_clause_is_not_treated_as_incidental_context(inspection):
    result, _, _ = localize(inspection, "突出猫，旁边的未知物件也作为主体")
    assert result.selection.status == "ambiguous"
    assert result.selection.selected_ids == []
    assert result.queries["task_scope"]["missing_semantic_units"]


def test_plural_people_requires_more_than_one_semantic_instance(inspection):
    result, _, _ = localize(inspection, "photograph people",
        [semantic("person_1", "person")], [candidate(label="person")])
    assert result.selection.status == "ambiguous"
    assert result.selection.selected_ids == []


def test_known_required_second_subject_without_box_does_not_select_first(inspection):
    result, _, _ = localize(inspection, "突出猫和狗",
        [semantic("cat_1", "cat"), semantic("dog_1", "dog")], [candidate()], ["cat_1"])
    assert result.selection.status == "ambiguous"
    assert result.selection.selected_ids == []


@pytest.mark.parametrize("main_id", ["cat_1", "dog_1"])
def test_required_target_omitted_from_main_ids_cannot_be_lost_from_protection(inspection, main_id):
    cat_box, dog_box = [.1, .1, .3, .3], [.6, .6, .8, .8]
    boxes = [candidate().model_copy(update={"bbox_native": cat_box,
              "bbox_postprocessed": cat_box, "bbox": cat_box}),
             candidate("det_dog", "dog").model_copy(update={"bbox_native": dog_box,
              "bbox_postprocessed": dog_box, "bbox": dog_box})]
    result, _, _ = localize(inspection, "突出猫和狗",
        [semantic("cat_1", "cat"), semantic("dog_1", "dog")], boxes, [main_id])
    assert result.selection.status == "ambiguous"
    assert result.selection.selected_ids == []
    assert result.selection.candidate_ids == ["det_cat", "det_dog"]
    assert result.queries["task_scope"]["missing_semantic_units"] == []
    assert [association["candidate_ids"] for association in result.selection.associations] == [
        ["det_cat"], ["det_dog"]]


def test_explicit_only_retention_request_is_subject_evidence(inspection):
    result, _, _ = localize(inspection, "只保留猫，背景不必识别")
    assert result.selection.status == "selected"
    assert result.selection.selected_ids == ["det_cat"]


def test_background_reflection_does_not_claim_main_cat_is_reflection(inspection):
    result, _, _ = localize(inspection, "突出猫，镜中的倒影仅作背景无需定位")
    assert result.selection.status == "selected"
    assert result.selection.selected_ids == ["det_cat"]


def test_detector_entity_claim_is_not_promoted_to_geometry_fact(inspection):
    box = candidate().model_copy(update={"entity_kind": "physical"})
    result, _, _ = localize(inspection, CAT_TASK, boxes=[box])
    assert result.selection.status == "selected"
    assert result.candidates[0].entity_kind == "unknown"
    assert result.detection.filtered_candidates[0].entity_kind == "physical"


def test_detector_special_entity_claim_prevents_category_identity_selection(inspection):
    box = candidate().model_copy(update={"entity_kind": "reflection"})
    result, _, _ = localize(inspection, CAT_TASK, boxes=[box])
    assert result.selection.status != "selected"
    assert result.selection.selected_ids == []
    assert result.candidates[0].entity_kind == "unknown"
