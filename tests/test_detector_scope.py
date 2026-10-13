"""Task support depends on requested units, never on background or references."""
import pytest

from vision_lab_tool import detector_runner as runner
from vision_lab_tool.detector_models import (
    DetectionObject,
    DetectionResult,
    DetectorConfig,
    SemanticObject,
    VLMSnapshot,
)
from vision_lab_tool.detector_queries import canonical, compose_queries
from vision_lab_tool.models import ModelConfig


def semantic(object_id, query, level="whole", entity="unknown", parent=None):
    return SemanticObject(object_id=object_id, query=query, label=query,
                          target_level=level, entity_kind=entity, parent_object_id=parent)


def candidate(object_id="det-cup", label="cup", level="instance"):
    box = [.2, .1, .8, .9]
    return DetectionObject(object_id=object_id, label_original=label, label_display=label,
                           bbox_native=box, bbox_postprocessed=box, bbox=box,
                           target_level=level, coordinate_basis="fixed offline fixture")


def associate(task, semantics, candidates=None, mains=None, detector="yolo26"):
    snapshot = VLMSnapshot(config=ModelConfig(name="offline", provider="fixture", protocol="mock"),
                           semantics=semantics, semantic_status="success", real=False,
                           selection_status="success", subject_status="selected",
                           main_subject_ids=mains if mains is not None else [semantics[0].object_id])
    objects = candidates if candidates is not None else [candidate()]
    detection = DetectionResult(config=DetectorConfig(detector=detector), status="success",
                                candidates=objects, filtered_candidates=objects, real=False)
    queries = compose_queries(task, semantics)
    return runner._associate(detection, snapshot, queries, "B2" if detector == "yolo26" else "B1")


def test_background_rock_does_not_turn_supported_cup_task_unsupported():
    cup = semantic("cup", "cup")
    before = associate("定位水杯", [cup])
    after = associate("定位水杯", [cup, semantic("background", "rock")])
    assert before.selection.status == "selected"
    assert after.selection.status == "selected"
    assert after.selection.selected_ids == before.selection.selected_ids
    assert after.unsupported_targets == []
    assert any(a["vlm_object_id"] == "background" and a["status"] == "unsupported"
               for a in after.selection.associations)


@pytest.mark.parametrize("query,task", [("rock", "定位水杯和礁石"),
                                      ("hand", "定位水杯和手部"),
                                      ("clay", "定位水杯和泥坯")])
def test_unselected_but_required_unsupported_units_stay_in_full_task(query, task):
    result = associate(task, [semantic("cup", "cup"), semantic("required", query)])
    assert result.selection.status == "unsupported"
    assert result.unsupported_targets
    assert not result.selection.selected_ids


def test_supported_but_missing_second_required_class_cannot_select_full_task():
    result = associate("定位水杯和瓶子 bottle", [semantic("cup", "cup")])
    assert result.selection.status == "ambiguous"
    assert not result.selection.selected_ids


def test_unknown_task_scope_cannot_be_inferred_from_main_ids():
    result = associate("定位主体与另一件未知物件", [semantic("cup", "cup")])
    assert result.selection.status == "ambiguous"
    assert not result.selection.selected_ids


def test_cup_inside_region_is_an_independent_required_unit():
    result = associate("定位水杯整体和杯中可见区域", [semantic("cup", "cup")])
    assert result.selection.status == "unsupported"
    assert any("region" in x for x in result.unsupported_targets)


def test_unknown_parts_required_by_task_cannot_be_filled_by_whole_box():
    result = associate("定位水杯整体与可见部件", [semantic("cup", "cup")])
    assert result.selection.status in {"unsupported", "ambiguous"}
    assert not result.selection.selected_ids


def test_water_cup_alias_is_safe_but_inside_region_is_not_cup():
    assert canonical("Water Cup.") == "cup"
    assert canonical("cup inside region") == "cup inside region"
    result = associate("定位水杯", [semantic("cup", "water cup")])
    assert result.selection.status == "selected"


def test_compound_detector_label_uses_complete_frozen_query_phrases():
    result = associate("定位水杯", [semantic("cup", "water cup")],
                       [candidate(label="cup water cup cup")], detector="grounding_dino")
    assert result.selection.status == "selected"
    assert result.candidates[0].label_original == "cup water cup cup"


@pytest.mark.parametrize("label", ["cup inside region", "cup handle", "cup unknownthing"])
def test_label_substring_cannot_impersonate_whole_cup(label):
    result = associate("定位水杯", [semantic("cup", "cup")],
                       [candidate(label=label)], detector="grounding_dino")
    assert not result.selection.selected_ids


def test_depicted_person_compound_can_associate_but_cannot_be_selected_as_live_person():
    result = associate("定位人物候选", [semantic("drawing", "cartoon woman", "instance", "depiction")],
                       [candidate(label="person cartoon woman")], detector="grounding_dino")
    assert result.selection.status == "ambiguous"
    assert not result.selection.selected_ids
    assert result.selection.associations[0]["candidate_ids"] == ["det-cup"]
    assert result.candidates[0].entity_kind == "unknown"


def test_multiple_same_class_instances_are_not_force_bound():
    result = associate("定位水杯", [semantic("cup", "water cup")],
                       [candidate(), candidate("second")])
    assert result.selection.status == "ambiguous"
    assert not result.selection.selected_ids


def test_part_cannot_be_substituted_by_whole_category_candidate():
    result = associate("定位杯子的部件", [semantic("part", "cup", "part")],
                       [candidate()], detector="grounding_dino")
    assert result.selection.status != "selected"
    assert result.candidates[0].target_level == "instance"


@pytest.mark.parametrize("task", ["定位水杯和螺丝", "locate cup and widget"])
def test_unrecognized_second_requested_noun_leaves_scope_unknown(task):
    result = associate(task, [semantic("cup", "cup")])
    assert result.selection.status == "ambiguous"
    assert result.queries["task_scope"]["status"] == "unknown"


def test_explicitly_unrequested_background_is_diagnostic_only():
    result = associate("定位水杯，背景礁石无需定位", [semantic("cup", "cup"),
                                                   semantic("rock", "rock")])
    assert result.selection.status == "selected"
    assert result.queries["task_scope"]["object_roles"][1]["role"] == "background"


def test_auxiliary_scale_object_is_distinct_from_required_object():
    result = associate("定位水杯，礁石仅作尺度关系上下文", [semantic("cup", "cup"),
                                                       semantic("rock", "rock")])
    assert result.selection.status == "selected"
    assert result.queries["task_scope"]["object_roles"][1]["role"] == "auxiliary"


def test_task_requests_two_hands_but_semantics_only_have_one():
    result = associate("定位两只手", [semantic("one", "hand", "instance")],
                       [candidate(label="hand")], detector="grounding_dino")
    assert result.selection.status == "ambiguous"
    assert "task:hand" in result.queries["task_scope"]["missing_semantic_units"]


def test_unknown_identity_never_replaces_known_identity_gate():
    result = associate("定位水杯", [semantic("cup", "water cup", entity="physical")])
    assert result.selection.status == "ambiguous"
    assert result.candidates[0].entity_kind == "unknown"


def test_alias_does_not_modify_frozen_candidates_or_semantics():
    objects = [candidate(label="cup water cup cup")]
    semantics = [semantic("cup", "water cup")]
    original_obj = objects[0].model_dump()
    original_sem = semantics[0].model_dump()
    result = associate("定位水杯", semantics, objects, detector="grounding_dino")
    assert objects[0].model_dump() == original_obj
    assert semantics[0].model_dump() == original_sem
    norm = result.queries["label_normalization"]["det-cup"]
    assert norm["original"] == "cup water cup cup" and norm["normalized"] == "cup"
    assert norm["rule_version"] and norm["basis"]


@pytest.mark.parametrize("task", ["定位茶壶和水杯", "locate widget and cup"])
def test_unknown_first_required_object_is_not_dropped_before_known_class(task):
    result = associate(task, [semantic("cup", "cup")])
    assert result.selection.status == "ambiguous"
    assert result.queries["task_scope"]["status"] == "unknown"
    assert any(u.get("support_status") == "unknown"
               for u in result.queries["task_scope"]["required_units"])


@pytest.mark.parametrize("task", ["定位两个水杯", "locate two cups", "定位2个水杯"])
def test_explicit_multiple_instances_require_all_instances(task):
    result = associate(task, [semantic("cup", "cup")])
    assert result.selection.status == "ambiguous"
    unit = result.queries["task_scope"]["required_units"][0]
    assert unit["minimum_count"] == 2
    assert unit["unit_id"] in result.queries["task_scope"]["missing_semantic_units"]


@pytest.mark.parametrize("task", ["定位杯子把手", "locate cup handle",
                                  "locate the screw beside the cup"])
def test_named_part_or_unknown_target_cannot_be_replaced_by_known_context(task):
    result = associate(task, [semantic("cup", "cup")])
    assert result.selection.status != "selected"
    assert result.queries["task_scope"]["missing_semantic_units"]


@pytest.mark.parametrize("task", ["locate cup, ignore widget and screw",
                                  "定位水杯，背景茶壶和螺丝无需定位",
                                  "定位水杯，徽标仅作上下文无需定位"])
def test_unknown_nouns_in_explicit_background_clause_do_not_block(task):
    result = associate(task, [semantic("cup", "cup")])
    assert result.selection.status == "selected"


@pytest.mark.parametrize("task", ["定位水杯旁边的茶壶", "locate cup beside a widget",
                                  "定位水杯上的标签", "locate cup region"])
def test_unparsed_target_modifier_after_known_class_keeps_scope_unknown(task):
    result = associate(task, [semantic("cup", "cup")])
    assert result.selection.status == "ambiguous"
    assert result.queries["task_scope"]["status"] == "unknown"
