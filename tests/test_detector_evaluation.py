import pytest

from vision_lab_tool.detector_evaluation import (
    aggregate,
    cost_totals,
    overall_summary,
    result_metrics,
    validate_review,
)
from vision_lab_tool.detector_models import (
    DetectionObject,
    DetectionResult,
    DetectorConfig,
    DetectorExperiment,
    DetectorReference,
    DetectorReview,
    GroundTruth,
    MethodResult,
    SubjectSelection,
    VLMSnapshot,
)
from vision_lab_tool.models import ModelConfig


def obj(object_id="person1", label="person", level="instance", box=None, entity="physical"):
    box = box or [0.1, 0.1, 0.8, 0.9]
    return DetectionObject(
        object_id=object_id,
        label_original=label,
        label_display=label,
        bbox_native=[10, 10, 80, 90],
        bbox_postprocessed=[10, 10, 80, 90],
        bbox=box,
        coordinate_basis="sent_pixels_to_normalized",
        target_level=level,
        entity_kind=entity,
    )


def experiment(candidates=None):
    candidates = candidates if candidates is not None else [obj()]
    result = MethodResult(
        method="B1", detector="grounding_dino", status="ok", candidates=candidates
    )
    result.selection = SubjectSelection(
        status="selected", selected_ids=[candidates[0].object_id] if candidates else []
    )
    return DetectorExperiment(
        mode="localization",
        experiment_version="evaluation-fixture-v1",
        task_prompt="person",
        task_prompt_sha256="task-hash",
        image={"original_sha256": "image-hash"},
        configs=[DetectorConfig(detector="grounding_dino")],
        results=[result],
    )


def annotate(run, refs=None):
    refs = (
        refs
        if refs is not None
        else [
            GroundTruth(
                gt_id="gt1",
                label="person",
                bbox=[0.1, 0.1, 0.8, 0.9],
                entity_kind="physical",
                confirmed=True,
                user_main_subject=True,
            )
        ]
    )
    run.reference = DetectorReference(complete=True, objects=refs, main_subject_judgeable=True)
    run.evaluations[run.results[0].result_id] = DetectorReview(reviewed=True)
    return run.evaluations[run.results[0].result_id]


def test_no_reference_or_unconfirmed_ai_reference_is_not_accuracy():
    run = experiment()
    run.reference.objects = [
        GroundTruth(gt_id="ai", label="person", bbox=[0, 0, 1, 1], annotation_source="ai")
    ]
    review = DetectorReview(reviewed=True, subject_correct_auto=True)
    run.evaluations[run.results[0].result_id] = review
    metrics = result_metrics(run, run.results[0])
    assert metrics["recall"] is None and metrics["mean_iou"] is None
    assert metrics["complete_task_success"] is None and metrics["subject_correct_auto"] is None
    assert metrics["candidate_usable"] is True
    assert metrics["unconfirmed_gt_count"] == 1
    with pytest.raises(ValueError, match="逐框人工确认"):
        DetectorReference(complete=True, objects=run.reference.objects)


def test_empty_complete_reference_cannot_enable_human_quality_metrics():
    run = experiment()
    run.reference = DetectorReference(complete=True)
    run.evaluations[run.results[0].result_id] = DetectorReview(reviewed=True)
    metrics = result_metrics(run, run.results[0])
    assert metrics["reference_ready"] is False
    assert metrics["tp"] is None and metrics["complete_task_success"] is None


def test_legacy_ai_confirmed_flag_without_human_source_is_not_human_truth():
    run = experiment()
    review = annotate(run)
    run.reference.objects[0].annotation_source = "ai"
    review.box_matches = {"person1": "gt1"}
    metrics = result_metrics(run, run.results[0])
    assert metrics["reference_ready"] is False and metrics["mean_iou"] is None
    assert metrics["tp"] is None and metrics["complete_task_success"] is None


def test_unanimous_compound_alias_has_same_pairing_and_fp_scope_as_single_class():
    run = experiment([obj("cup1", "cup water cup cup", "whole")])
    result = run.results[0]
    result.queries = {"merged": ["cup", "water cup"]}
    review = annotate(run, [GroundTruth(
        gt_id="gt-cup", label="cup", bbox=[.1, .1, .8, .9], target_level="whole",
        confirmed=True, annotation_source="human", entity_kind="physical")])
    review.box_matches = {"cup1": "gt-cup"}
    validate_review(run, result, review)
    metrics = result_metrics(run, result)
    assert metrics["tp"] == 1 and metrics["mean_iou"] == 1
    assert metrics["in_scope_prediction_count"] == 1
    assert result.candidates[0].label_original == "cup water cup cup"


@pytest.mark.parametrize("label,queries", [
    ("person cartoon woman", ["person", "cartoon woman"]),
    ("cup inside region", ["cup", "cup inside region"]),
])
def test_mixed_identity_or_region_compound_cannot_pair_to_whole_category(label, queries):
    run = experiment([obj("pred", label, "whole")])
    result = run.results[0]
    result.queries = {"merged": queries}
    review = annotate(run, [GroundTruth(
        gt_id="gt", label="person" if label.startswith("person") else "cup",
        bbox=[.1, .1, .8, .9], target_level="whole", confirmed=True)])
    review.box_matches = {"pred": "gt"}
    with pytest.raises(ValueError, match="类别不同"):
        validate_review(run, result, review)


def test_managed_reference_missing_required_unit_cannot_shrink_denominator():
    run = experiment()
    annotate(run)
    run.provenance["reference_workflow"] = {
        "version": "human-reference-workflow-v1", "required_gt_ids": ["gt1", "gt2"],
        "confirmation_log": [], "pairing_confirmations": {},
    }
    metrics = result_metrics(run, run.results[0])
    assert metrics["reference_ready"] is False
    assert metrics["tp"] is None and metrics["complete_task_success"] is None


def test_managed_ai_pair_draft_does_not_become_human_metrics_when_reviewed():
    run = experiment()
    review = annotate(run)
    review.box_matches = {"person1": "gt1"}
    run.provenance["reference_workflow"] = {
        "version": "human-reference-workflow-v1", "required_gt_ids": ["gt1"],
        "confirmation_log": [{"gt_id": "gt1", "object_sha256": "fixture"}],
        "pairing_confirmations": {},
    }
    metrics = result_metrics(run, run.results[0])
    assert metrics["scoring_ready"] is False
    assert metrics["mean_iou"] is None and metrics["tp"] is None


def test_manual_pair_low_iou_remains_in_distribution_and_is_fp_plus_fn():
    run = experiment([obj(box=[0.1, 0.1, 0.3, 0.3])])
    review = annotate(run)
    review.box_matches = {"person1": "gt1"}
    metrics = result_metrics(run, run.results[0])
    assert metrics["paired_count"] == 1 and 0 < metrics["mean_iou"] < 0.5
    assert (metrics["tp"], metrics["fp"], metrics["fn"]) == (0, 1, 1)
    assert metrics["usable_box_coverage"] == 1
    assert metrics["recall"] == 0 and metrics["complete_task_success"] is False


def test_failure_empty_and_unsupported_keep_all_gt_in_denominator():
    run = experiment([])
    refs = [
        GroundTruth(gt_id="a", label="person", bbox=[0, 0, 0.5, 0.5], confirmed=True),
        GroundTruth(
            gt_id="b", label="hand", bbox=[0.5, 0.5, 1, 1], confirmed=True, target_level="part"
        ),
    ]
    annotate(run, refs)
    run.results[0].status = "timeout"
    run.results[0].unsupported_targets = ["hand"]
    run.evaluations.clear()  # known runtime failure can score zero delivery with confirmed GT
    metrics = result_metrics(run, run.results[0])
    assert (metrics["tp"], metrics["fp"], metrics["fn"]) == (0, 0, 2)
    assert metrics["precision"] is None and metrics["recall"] == 0
    assert metrics["candidate_usable"] is False and metrics["complete_task_success"] is False


@pytest.mark.parametrize("changed", ["label", "level", "entity"])
def test_pair_requires_same_class_level_entity(changed):
    run = experiment(
        [
            obj(
                label="hand" if changed == "label" else "person",
                level="part" if changed == "level" else "instance",
                entity="depiction" if changed == "entity" else "physical",
            )
        ]
    )
    review = annotate(run)
    review.box_matches = {"person1": "gt1"}
    review.in_scope_pred_ids = ["person1"]
    with pytest.raises(ValueError, match="不同"):
        validate_review(run, run.results[0], review)
    metrics = result_metrics(run, run.results[0])
    assert (metrics["tp"], metrics["fp"], metrics["fn"]) == (0, 1, 1)
    assert metrics["mean_iou"] is None


def test_duplicate_predictions_have_one_tp_and_explicit_invalid_mapping():
    run = experiment([obj(), obj("person2")])
    review = annotate(run)
    review.box_matches = {"person1": "gt1", "person2": "gt1"}
    with pytest.raises(ValueError, match="一对一"):
        validate_review(run, run.results[0], review)
    metrics = result_metrics(run, run.results[0])
    assert (metrics["tp"], metrics["fp"], metrics["fn"]) == (1, 1, 0)
    assert metrics["paired_count"] == 1 and metrics["validation_errors"]


def test_overlapping_whole_and_part_stay_distinct_and_background_is_out_of_scope():
    run = experiment(
        [
            obj(),
            obj("hand1", "hand", "part", [0.2, 0.2, 0.4, 0.4]),
            obj("background", "chair", box=[0.2, 0.2, 0.4, 0.4]),
            obj("ignored", "person", box=[0.8, 0, 1, 0.2]),
        ]
    )
    review = annotate(
        run,
        [
            GroundTruth(
                gt_id="gt1",
                label="person",
                bbox=[0.1, 0.1, 0.8, 0.9],
                entity_kind="physical",
                confirmed=True,
            ),
            GroundTruth(
                gt_id="gt2",
                label="hand",
                bbox=[0.2, 0.2, 0.4, 0.4],
                target_level="part",
                parent_id="gt1",
                entity_kind="physical",
                confirmed=True,
            ),
            GroundTruth(
                gt_id="ignore", label="person", bbox=[0.8, 0, 1, 0.2], ignore=True, confirmed=True
            ),
        ],
    )
    review.box_matches = {"person1": "gt1", "hand1": "gt2", "ignored": "ignore"}
    metrics = result_metrics(run, run.results[0])
    assert (metrics["tp"], metrics["fp"], metrics["fn"]) == (2, 0, 0)
    assert metrics["out_of_scope_prediction_count"] == 1
    assert metrics["ignored_prediction_count"] == 1 and metrics["ignored_gt_count"] == 1


def test_manual_and_automatic_subject_conditions_remain_separate():
    run = experiment()
    review = annotate(run)
    review.box_matches = {"person1": "gt1"}
    review.subject_correct_auto = False
    review.subject_correct_human = True
    review.human_selected_ids = ["person1"]
    metrics = result_metrics(run, run.results[0])
    assert metrics["subject_correct_auto"] is False and metrics["subject_correct_human"] is True
    assert (
        metrics["complete_task_success"] is False and metrics["complete_task_success_human"] is True
    )
    assert run.results[0].selection.selected_ids == ["person1"]


def test_query_and_support_coverage_are_reviewed_independently_of_detections():
    run = experiment()
    review = annotate(
        run,
        [
            GroundTruth(
                gt_id="gt1",
                label="person",
                bbox=[0.1, 0.1, 0.8, 0.9],
                confirmed=True,
                entity_kind="physical",
            ),
            GroundTruth(
                gt_id="gt2",
                label="hand",
                bbox=[0.2, 0.2, 0.4, 0.4],
                confirmed=True,
                target_level="part",
                entity_kind="physical",
            ),
        ],
    )
    review.box_matches = {"person1": "gt1"}
    metrics = result_metrics(run, run.results[0])
    assert metrics["query_target_coverage"] is None
    review.query_covered_gt_ids = ["gt1", "gt2"]
    review.support_gt_ids = ["gt1"]
    metrics = result_metrics(run, run.results[0])
    assert metrics["query_target_coverage"] == 1
    assert metrics["fixed_class_support_coverage"] == 0.5
    assert metrics["fn"] == 1 and metrics["supported_subset"]["recall"] == 1


def test_detection_only_never_becomes_complete_selection_even_with_good_boxes():
    run = experiment()
    review = annotate(run)
    review.box_matches = {"person1": "gt1"}
    review.subject_correct_auto = True
    run.results[0].selection.status = "detection_only"
    metrics = result_metrics(run, run.results[0])
    assert metrics["mean_iou"] == 1 and metrics["complete_task_success"] is False


def test_edge_retention_requires_95_percent_and_iou_not_manual_override():
    run = experiment([obj(box=[0.1, 0.1, 0.77, 0.9])])
    review = annotate(run)
    review.box_matches = {"person1": "gt1"}
    review.subject_correct_auto = True
    run.reference.boundary_required = True
    metrics = result_metrics(run, run.results[0])
    assert metrics["edge_preserved"] is True
    run.results[0].candidates[0].bbox = [0.1, 0.1, 0.7, 0.9]
    review.edge_preserved = True
    metrics = result_metrics(run, run.results[0])
    assert metrics["edge_preserved"] is False and metrics["complete_task_success"] is False


def test_aggregate_separates_mock_split_and_retains_failure_tasks():
    success = experiment()
    review = annotate(success)
    review.box_matches = {"person1": "gt1"}
    review.subject_correct_auto = True
    failure = success.model_copy(deep=True)
    failure.results[0].status = "timeout"
    failure.results[0].candidates = []
    failure.results[0].selection = SubjectSelection()
    failure.evaluations.clear()
    failure.results[0].stages = {"detector": "timeout"}
    failure.results[0].timings = {"total": 180}
    summary = aggregate([success, failure])[0]
    assert summary["tasks"] == 2 and summary["fn"] == 1
    assert summary["complete_task"] == {
        "success": 1,
        "denominator": 2,
        "evaluated": 2,
        "unknown": 0,
        "rate": 0.5,
    }
    assert summary["stages"]["detector"]["timeout"] == 1
    assert summary["timings"]["total"]["max"] == 180
    failure.simulated = True
    assert len(aggregate([success, failure])) == 1
    assert len(aggregate([success, failure], include_simulated=True)) == 2


def test_shared_vlm_cost_once_and_unknown_is_not_zero():
    run = experiment()
    run.vlm = VLMSnapshot(
        config=ModelConfig(name="vlm", provider="local fixture", protocol="mock"),
        real=True,
        attempts=[{"request_sent": True}],
    )
    copy = run.model_copy(deep=True)
    totals = cost_totals([run, copy])
    assert totals["shared_vlm_calls"] == 1 and totals["currencies"]["CNY"]["unknown_calls"] == 1
    assert totals["local_compute_cost"] is None
    run.vlm.cost = {"amount": 0.1, "currency": "CNY"}
    copy.vlm.cost = run.vlm.cost
    totals = cost_totals([run, copy])
    assert totals["currencies"]["CNY"]["known_amount"] == 0.1


def test_unsent_or_unstarted_vlm_request_is_not_billed_as_unknown():
    run = experiment()
    run.vlm = VLMSnapshot(
        config=ModelConfig(name="vlm", provider="test", protocol="chat"),
        real=True,
        attempts=[{"status": "configuration_error", "request_sent": False}],
    )
    assert cost_totals([run])["shared_vlm_calls"] == 0
    assert cost_totals([run])["currencies"] == {}
    run.vlm.attempts = []
    assert cost_totals([run])["shared_vlm_calls"] == 0
    # Older detector records without request_sent remain charge-unknown attempts.
    run.vlm.attempts = [{"status": "timeout"}]
    assert cost_totals([run])["currencies"]["CNY"]["unknown_calls"] == 1


def test_unknown_entity_manual_geometry_pair_does_not_claim_entity_correctness():
    run = experiment([obj(entity="unknown")])
    run.results[0].candidates[0].label_display = "人物"
    run.results[0].candidates[0].label_original = "people"
    review = annotate(run)
    review.box_matches = {"person1": "gt1"}
    review.subject_correct_auto = True
    validate_review(run, run.results[0], review)
    metrics = result_metrics(run, run.results[0])
    assert metrics["tp"] == 1 and metrics["mean_iou"] == 1
    assert metrics["entity_kind_accuracy"] == 0
    assert metrics["entity_kind_prediction_unknown_count"] == 1
    assert metrics["complete_task_success"] is False


def test_grouping_ignores_image_dimensions_cache_flags_and_preserves_provenance():
    first = experiment()
    review = annotate(first)
    review.box_matches = {"person1": "gt1"}
    review.subject_correct_auto = True
    review.query_covered_gt_ids = ["gt1"]
    review.support_gt_ids = ["gt1"]
    first.results[0].detection = DetectionResult(
        config=first.configs[0],
        status="success",
        candidates=first.results[0].candidates,
        metadata={
            "weights": [{"sha256": "frozen"}],
            "source_image_size": [100, 100],
            "actual_input_size": [640, 640],
            "model_load_cache_hit": False,
        },
    )
    second = first.model_copy(deep=True)
    second.image["original_sha256"] = "another-image"
    second.results[0].detection.metadata.update(
        source_image_size=[200, 300],
        actual_input_size=[640, 960],
        model_load_cache_hit=True,
    )
    summaries = aggregate([first, second])
    assert len(summaries) == 1 and summaries[0]["tasks"] == 2
    assert summaries[0]["query_target_coverage"]["covered"] == 2
    assert summaries[0]["query_target_coverage"]["denominator"] == 2
    second.results[0].detection.metadata["weights"] = [{"sha256": "changed"}]
    assert len(aggregate([first, second])) == 2


@pytest.mark.parametrize(
    "status", ["schema_error", "coordinate_error", "runtime_error", "device_unavailable"]
)
def test_fatal_status_does_not_claim_operational_candidate_availability(status):
    run = experiment()
    run.results[0].status = status
    assert result_metrics(run, run.results[0])["candidate_usable"] is False
    run.results[0].status = "partial_coordinates"
    assert result_metrics(run, run.results[0])["candidate_usable"] is True


def test_query_source_coverage_is_independent_and_missing_remains_unknown():
    run = experiment()
    review = annotate(run)
    review.query_covered_gt_ids_by_source = {
        "from_task": [],
        "from_vlm": ["gt1"],
        "merged": ["gt1"],
    }
    metrics = result_metrics(run, run.results[0])
    assert metrics["query_coverage_by_source"]["from_task"]["rate"] == 0
    assert metrics["query_coverage_by_source"]["from_vlm"]["rate"] == 1
    assert metrics["query_coverage_by_source"]["fallback"]["rate"] is None
    assert metrics["query_target_coverage"] == 1
    summary = aggregate([run])[0]
    assert summary["query_coverage_by_source"]["from_task"]["denominator"] == 1
    assert summary["query_coverage_by_source"]["fallback"]["missing_tasks"] == 1
    review.query_covered_gt_ids_by_source["from_task"] = ["missing"]
    with pytest.raises(ValueError, match="查询覆盖"):
        validate_review(run, run.results[0], review)


def test_pure_candidate_only_and_unspecified_subject_do_not_claim_full_success():
    run = experiment()
    review = annotate(run)
    review.box_matches = {"person1": "gt1"}
    review.subject_correct_auto = True
    run.mode = "pure_detection"
    assert result_metrics(run, run.results[0])["complete_task_success"] is False
    run.mode = "localization"
    run.reference.main_subject_judgeable = False
    assert result_metrics(run, run.results[0])["complete_task_success"] is None
    run.results[0].status = "timeout"
    assert result_metrics(run, run.results[0])["complete_task_success"] is False


def test_overall_all_planned_denominator_survives_missing_actual_provenance_and_different_tasks():
    success = experiment()
    review = annotate(success)
    review.box_matches = {"person1": "gt1"}
    review.subject_correct_auto = True
    success.results[0].detection = DetectionResult(
        config=success.configs[0],
        status="success",
        candidates=success.results[0].candidates,
        metadata={"weights": [{"sha256": "actual-success"}]},
    )
    failure = success.model_copy(deep=True)
    failure.evaluations.clear()
    failure.results[0].status = "environment_missing"
    failure.results[0].candidates = []
    failure.results[0].selection = SubjectSelection()
    failure.results[0].detection = DetectionResult(
        config=failure.configs[0], status="environment_missing"
    )
    failure.results[0].stages = {"detector": "environment_missing"}
    pending = failure.model_copy(deep=True)
    pending.task_prompt_sha256 = "a-different-task"
    pending.results[0].status = "pending"
    pending.results[0].detection = None
    pending.results[0].stages = {"detector": "pending"}
    summaries = overall_summary([success, failure, pending])
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["scope"] == "all_planned_requested_configuration"
    assert summary["tasks"] == summary["planned_tasks"] == 3
    assert summary["distinct_tasks"] == 2
    assert summary["task_prompt_sha256s"] == ["a-different-task", "task-hash"]
    assert summary["gt_count_confirmed"] == summary["gt_count_evaluated"] == 3
    assert (summary["tp"], summary["fp"], summary["fn"]) == (1, 0, 2)
    assert summary["recall"] == pytest.approx(1 / 3)
    assert summary["candidate_usable"]["denominator"] == 3
    assert summary["candidate_usable"]["success"] == 1
    assert summary["complete_task"]["success"] == 1
    assert summary["complete_task"]["denominator"] == 3
    assert summary["stages"]["detector"] == {"environment_missing": 1, "pending": 1}
    assert len(aggregate([success, failure, pending])) > 1  # provenance subgroups still explicit


def test_overall_unknown_review_and_reference_stay_unknown_with_explicit_denominators():
    first = experiment()
    review = annotate(first)
    review.box_matches = {"person1": "gt1"}
    review.subject_correct_auto = True
    unreviewed = first.model_copy(deep=True)
    unreviewed.evaluations.clear()
    missing_reference = first.model_copy(deep=True)
    missing_reference.reference.complete = False
    summary = overall_summary([first, unreviewed, missing_reference])[0]
    assert summary["planned_tasks"] == 3
    assert summary["quality_evaluated_tasks"] == 1 and summary["quality_unknown_tasks"] == 2
    assert summary["reference_missing"] == 1
    assert summary["gt_count_confirmed"] == 2 and summary["gt_count_unevaluated"] == 1
    assert summary["recall"] is None and summary["evaluated_recall"] == 1
    assert summary["complete_task"] == {
        "success": 1,
        "denominator": 3,
        "evaluated": 1,
        "unknown": 2,
        "rate": None,
    }
    assert summary["subject_human"]["unknown"] == 3


def test_overall_separates_requested_settings_mock_split_and_flags_partial_coordinates():
    first = experiment()
    second = first.model_copy(deep=True)
    second.results[0].status = "partial_coordinates"
    second.results[0].detection = DetectionResult(
        config=second.configs[0], status="partial_coordinates"
    )
    assert overall_summary([first, second])[0]["partial_coordinate_tasks"] == 1
    assert overall_summary([first, second])[0]["candidate_usable"]["success"] == 2
    second.configs[0].device = "cuda:0"
    assert len(overall_summary([first, second])) == 2
    second = first.model_copy(deep=True)
    second.dataset_split = "验证"
    assert len(overall_summary([first, second])) == 2
    second.dataset_split = "开发"
    second.simulated = True
    assert len(overall_summary([first, second])) == 1
    assert len(overall_summary([first, second], include_simulated=True)) == 2
