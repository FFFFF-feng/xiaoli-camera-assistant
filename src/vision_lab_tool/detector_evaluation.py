"""Confirmed-reference evaluation, separate from legacy visual-model scores.

Correspondence is supplied by a human, never chosen by highest IoU. A legal pair
can have a poor IoU; the pair remains in the IoU distribution and counts as FP/FN
below the frozen threshold. Unknown quality is never filled in with a score.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from statistics import mean, median

from vision_lab_tool.detector_models import DetectorExperiment, DetectorReview, MethodResult
from vision_lab_tool.detector_queries import canonical, label_components
from vision_lab_tool.detector_reference import pairing_ready, reference_ready
from vision_lab_tool.evaluation import iou

IOU_THRESHOLD = 0.5
EDGE_COVERAGE_THRESHOLD = 0.95
EVALUATION_RULE_VERSION = "human-correspondence-class-level-entity-v2"
QUERY_SOURCES = ("from_task", "from_vlm", "fallback", "manual", "merged")
FAILED_STATUSES = {
    "pending",
    "not_attempted",
    "not_sent",
    "cancelled",
    "timeout",
    "error",
    "missing_environment",
    "missing_weights",
    "model_missing",
    "worker_error",
    "http_error",
    "network_error",
    "json_error",
    "invalid_box",
    "transform_error",
    "authentication",
    "refused",
    "truncated",
    "device_unavailable",
    "unsupported_device",
}


def _label(label: str) -> str:
    return canonical(label)


def _prediction_label(result, pred):
    normalized = label_components(pred.label_original, result.queries.get("merged", []))
    # Only unanimous complete phrases share a class. Mixed identity/category
    # labels remain unmatched rather than selecting a convenient component.
    if len(normalized["components"]) == 1:
        return normalized["components"][0]
    return _label(pred.label_original)


def _reference_ready(run: DetectorExperiment) -> bool:
    return reference_ready(run)


def _targets(run: DetectorExperiment) -> dict:
    return {
        o.gt_id: o
        for o in run.reference.objects
        if o.confirmed and o.judgeable and not o.ignore and not o.out_of_scope
    }


def _review_errors(run, result, review) -> list[str]:
    errors = []
    preds = {p.object_id: p for p in result.candidates}
    refs = {g.gt_id: g for g in run.reference.objects}
    used = set()
    for pred_id, gt_id in review.box_matches.items():
        if pred_id not in preds or gt_id not in refs:
            errors.append(f"配对引用不存在: {pred_id} → {gt_id}")
            continue
        if gt_id in used:
            errors.append(f"一对一配对违反: 真值 {gt_id} 重复配对")
        used.add(gt_id)
        pred, gt = preds[pred_id], refs[gt_id]
        if _prediction_label(result, pred) != _label(gt.label):
            errors.append(f"配对类别不同: {pred_id} → {gt_id}")
        if pred.target_level != gt.target_level:
            errors.append(f"配对目标层级不同: {pred_id} → {gt_id}")
        if (
            pred.entity_kind != "unknown"
            and gt.entity_kind != "unknown"
            and pred.entity_kind != gt.entity_kind
        ):
            errors.append(f"配对实体归属不同: {pred_id} → {gt_id}")
        if not gt.confirmed:
            errors.append(f"配对真值尚未人工确认: {gt_id}")
    for field in ("human_selected_ids", "ignored_pred_ids", "in_scope_pred_ids"):
        ids = getattr(review, field)
        if ids is not None:
            if len(ids) != len(set(ids)):
                errors.append(f"{field} 包含重复 ID")
            if any(v not in preds for v in ids):
                errors.append(f"{field} 引用不存在的候选 ID")
    for field in ("query_covered_gt_ids", "support_gt_ids"):
        ids = getattr(review, field)
        if ids is not None and (len(ids) != len(set(ids)) or any(v not in refs for v in ids)):
            errors.append(f"{field} 包含重复或不存在的真值 ID")
    for source, ids in review.query_covered_gt_ids_by_source.items():
        if source not in QUERY_SOURCES:
            errors.append(f"查询覆盖来源未知: {source}")
        if len(ids) != len(set(ids)) or any(v not in refs for v in ids):
            errors.append(f"查询覆盖 {source} 包含重复或不存在的真值 ID")
    if len({e.error_id for e in review.errors}) != len(review.errors):
        errors.append("错误条目 error_id 重复")
    return errors


def validate_review(run: DetectorExperiment, result: MethodResult, review: DetectorReview) -> None:
    """Reject invalid correspondence before saving a human review."""
    errors = _review_errors(run, result, review)
    if errors:
        raise ValueError("；".join(errors))


def _containment(pred: list[float], gt: list[float]) -> float:
    area = (gt[2] - gt[0]) * (gt[3] - gt[1])
    width = max(0.0, min(pred[2], gt[2]) - max(pred[0], gt[0]))
    height = max(0.0, min(pred[3], gt[3]) - max(pred[1], gt[1]))
    return width * height / area


def _failed(result: MethodResult) -> bool:
    return result.status in FAILED_STATUSES or any(
        token in result.status.casefold()
        for token in ("error", "timeout", "missing", "invalid", "unavailable")
    )


def result_metrics(
    run: DetectorExperiment, result: MethodResult, threshold: float = IOU_THRESHOLD
) -> dict:
    if not 0 <= threshold <= 1:
        raise ValueError("IoU 阈值必须为 0～1")
    review = run.evaluations.get(result.result_id, DetectorReview())
    ready = _reference_ready(run)
    targets = _targets(run) if ready else {}
    required = {k: v for k, v in targets.items() if v.required}
    preds = {o.object_id: o for o in result.candidates}
    errors = _review_errors(run, result, review)
    pairs_confirmed = pairing_ready(run, result, review)
    scoring_ready = ready and (
        (review.reviewed and pairs_confirmed) or _failed(result) or not preds
    )
    metrics = {
        "rule_version": EVALUATION_RULE_VERSION,
        "iou_threshold": threshold,
        "edge_coverage_threshold": EDGE_COVERAGE_THRESHOLD,
        "reference_ready": ready,
        "reviewed": review.reviewed,
        "pairing_confirmed": pairs_confirmed,
        "scoring_ready": scoring_ready,
        "validation_errors": errors,
        "gt_count": len(targets) if ready else None,
        "required_gt_count": len(required) if ready else None,
        "task_required_gt_count": sum(g.required for g in run.reference.objects),
        "excluded_required_gt_count": sum(
            g.required and (g.ignore or not g.judgeable or g.out_of_scope)
            for g in run.reference.objects
        ),
        "ignored_gt_count": sum(g.confirmed and g.ignore for g in run.reference.objects),
        "unjudgeable_gt_count": sum(g.confirmed and not g.judgeable for g in run.reference.objects),
        "unconfirmed_gt_count": sum(not g.confirmed for g in run.reference.objects),
        "prediction_count": len(preds),
        "in_scope_prediction_count": None,
        "out_of_scope_prediction_count": None,
        "ignored_prediction_count": len(review.ignored_pred_ids),
        "tp": None,
        "fp": None,
        "fn": None,
        "precision": None,
        "recall": None,
        "false_positive_fraction": None,
        "ious": [],
        "paired_count": 0,
        "missing_pairs": len(targets) if ready else None,
        "mean_iou": None,
        "median_iou": None,
        "query_target_coverage": None,
        "query_covered_count": None,
        "query_coverage_by_source": {
            source: {"covered": None, "denominator": len(required) if ready else None, "rate": None}
            for source in QUERY_SOURCES
        },
        "fixed_class_support_coverage": None,
        "supported_gt_count": None,
        "usable_box_coverage": None,
        "usable_box_count": None,
        "candidate_usable": bool(preds) and not _failed(result),
        "subject_correct_auto": None,
        "subject_correct_human": None,
        "ambiguity_correct": None,
        "entity_kind_accuracy": None,
        "entity_kind_gt_count": None,
        "entity_kind_correct_count": None,
        "entity_kind_prediction_known_count": None,
        "entity_kind_prediction_unknown_count": None,
        "edge_preserved": None,
        "edge_coverage": {},
        "complete_task_success": None,
        "complete_task_success_human": None,
        "supported_subset": None,
    }
    if not scoring_ready:
        return metrics

    # Required selection and explicit human scope keep wrong-class task outputs
    # in the FP denominator; other unannotated background is out_of_scope.
    selected = set(result.selection.selected_ids) | set(review.human_selected_ids)
    labels = {(_label(g.label), g.target_level) for g in targets.values()}
    scope = (
        set(review.in_scope_pred_ids)
        if review.in_scope_pred_ids is not None
        else {
            p.object_id
            for p in preds.values()
            if (_prediction_label(result, p), p.target_level) in labels
        }
    )
    scope.update(selected)
    scope.update(review.box_matches)
    scope.intersection_update(preds)
    ignored = set(review.ignored_pred_ids)
    all_refs = {g.gt_id: g for g in run.reference.objects}
    ignored.update(
        pred_id
        for pred_id, gt_id in review.box_matches.items()
        if gt_id in all_refs and (all_refs[gt_id].ignore or not all_refs[gt_id].judgeable)
    )
    scope.difference_update(ignored)
    metrics["candidate_usable"] = bool(scope) and not _failed(result)
    metrics["in_scope_prediction_count"] = len(scope)
    metrics["ignored_prediction_count"] = len(ignored & preds.keys())
    metrics["out_of_scope_prediction_count"] = len(preds.keys() - scope - ignored)

    paired = {}
    used_gt = set()
    for pred_id, gt_id in review.box_matches.items():
        if pred_id not in scope or gt_id not in targets or gt_id in used_gt:
            continue
        pred, gt = preds[pred_id], targets[gt_id]
        if (
            _prediction_label(result, pred) != _label(gt.label)
            or pred.target_level != gt.target_level
            or (
                pred.entity_kind != "unknown"
                and gt.entity_kind != "unknown"
                and pred.entity_kind != gt.entity_kind
            )
        ):
            continue
        used_gt.add(gt_id)
        paired[gt_id] = (pred_id, iou(pred.bbox, gt.bbox))
    values = [value for _, value in paired.values()]
    tp_gt = {gt_id for gt_id, (_, value) in paired.items() if value >= threshold}
    tp = len(tp_gt)
    metrics.update(
        {
            "tp": tp,
            "fp": len(scope) - tp,
            "fn": len(targets) - tp,
            "precision": tp / len(scope) if scope else None,
            "false_positive_fraction": (len(scope) - tp) / len(scope) if scope else None,
            "recall": tp / len(targets) if targets else None,
            "ious": values,
            "paired_count": len(values),
            "missing_pairs": len(targets) - len(values),
            "mean_iou": mean(values) if values else None,
            "median_iou": median(values) if values else None,
            "usable_box_coverage": len(paired) / len(targets) if targets else None,
            "usable_box_count": len(paired),
        }
    )
    for field, key in (
        ("query_covered_gt_ids", "query_target_coverage"),
        ("support_gt_ids", "fixed_class_support_coverage"),
    ):
        ids = getattr(review, field)
        if ids is not None:
            count = len(set(ids) & required.keys())
            metrics[key] = count / len(required) if required else None
            metrics[
                "query_covered_count" if field == "query_covered_gt_ids" else "supported_gt_count"
            ] = count
    if review.support_gt_ids is not None:
        supported = set(review.support_gt_ids) & targets.keys()
        metrics["supported_subset"] = {
            "gt_count": len(supported),
            "tp": len(tp_gt & supported),
            "fn": len(supported - tp_gt),
            "recall": len(tp_gt & supported) / len(supported) if supported else None,
        }
    for source, ids in review.query_covered_gt_ids_by_source.items():
        if source in QUERY_SOURCES:
            count = len(set(ids) & required.keys())
            metrics["query_coverage_by_source"][source] = {
                "covered": count,
                "denominator": len(required),
                "rate": count / len(required) if required else None,
            }
            if source == "merged" and review.query_covered_gt_ids is None:
                metrics["query_covered_count"] = count
                metrics["query_target_coverage"] = count / len(required) if required else None

    if run.reference.main_subject_judgeable:
        for condition, ids, declared in (
            ("auto", result.selection.selected_ids, review.subject_correct_auto),
            ("human", review.human_selected_ids, review.subject_correct_human),
        ):
            if condition == "human" and not ids and declared is None:
                continue
            available = bool(ids) and all(v in scope for v in ids)
            if condition == "auto" and result.selection.status != "selected":
                available = False
            if not available or _failed(result):
                metrics[f"subject_correct_{condition}"] = False
            elif declared is not None:
                metrics[f"subject_correct_{condition}"] = declared
    if run.reference.ambiguity_expected:
        metrics["ambiguity_correct"] = (
            result.selection.status == "ambiguous"
            and not result.selection.selected_ids
            and not _failed(result)
        )

    known_entity_targets = {k for k, g in targets.items() if g.entity_kind != "unknown"}
    entity_correct = {
        gt_id
        for gt_id in known_entity_targets & paired.keys()
        if preds[paired[gt_id][0]].entity_kind == targets[gt_id].entity_kind
    }
    metrics["entity_kind_gt_count"] = len(known_entity_targets)
    metrics["entity_kind_correct_count"] = len(entity_correct)
    metrics["entity_kind_prediction_known_count"] = sum(
        preds[p].entity_kind != "unknown" for p in scope
    )
    metrics["entity_kind_prediction_unknown_count"] = sum(
        preds[p].entity_kind == "unknown" for p in scope
    )
    if known_entity_targets:
        metrics["entity_kind_accuracy"] = len(entity_correct) / len(known_entity_targets)
    if run.reference.boundary_required:
        coverages = {
            gt_id: _containment(preds[paired[gt_id][0]].bbox, gt.bbox)
            for gt_id, gt in required.items()
            if gt_id in paired
        }
        metrics["edge_coverage"] = coverages
        metrics["edge_preserved"] = (
            bool(required)
            and all(
                gt_id in tp_gt and coverages.get(gt_id, 0) >= EDGE_COVERAGE_THRESHOLD
                for gt_id in required
            )
            and review.edge_preserved is not False
        )

    # Failures and unsupported units stay in the complete task denominator.
    good_boxes = bool(required) and required.keys() <= tp_gt
    complete_base = (
        good_boxes
        and not metrics["excluded_required_gt_count"]
        and (known_entity_targets & required.keys()) <= entity_correct
        and not errors
        and not _failed(result)
        and result.selection.status not in {"detection_only", "unsupported"}
        and not result.unsupported_targets
        and (not run.reference.boundary_required or metrics["edge_preserved"] is True)
    )
    for condition in ("auto", "human"):
        subject = metrics[f"subject_correct_{condition}"]
        if run.reference.main_subject_judgeable:
            if subject is None and complete_base:
                complete = None
            else:
                complete = complete_base and subject is True
        elif run.reference.ambiguity_expected:
            complete = complete_base and metrics["ambiguity_correct"] is True
        else:
            # A reference without either a judgeable main target or an explicit
            # ambiguity criterion cannot establish full subject correctness.
            complete = None if complete_base else False
        if condition == "auto" and run.mode == "pure_detection":
            complete = False
        if (
            condition == "human"
            and not review.human_selected_ids
            and review.subject_correct_human is None
        ):
            complete = None
        key = "complete_task_success" if condition == "auto" else "complete_task_success_human"
        metrics[key] = complete
    return metrics


def _rate(values) -> dict:
    values = list(values)
    known = [v for v in values if v is not None]
    return {
        "success": sum(v is True for v in known),
        "denominator": len(values),
        "evaluated": len(known),
        "unknown": len(values) - len(known),
        "rate": mean(known) if known and len(known) == len(values) else None,
    }


def _coverage(metrics: list[dict], count_key: str, denominator_key: str) -> dict:
    denominator = sum(m[denominator_key] or 0 for m in metrics)
    missing = sum(m[count_key] is None for m in metrics)
    covered = sum(m[count_key] or 0 for m in metrics)
    return {
        "covered": covered,
        "denominator": denominator,
        "evaluated_tasks": len(metrics) - missing,
        "missing_tasks": missing,
        "rate": covered / denominator if denominator and not missing else None,
    }


def aggregate(
    runs: list[DetectorExperiment],
    include_simulated: bool = False,
    *,
    include_mock: bool | None = None,
) -> list[dict]:
    if include_mock is not None:
        include_simulated = include_mock
    groups = defaultdict(list)
    for run in runs:
        for result in run.results:
            simulated = run.simulated or not result.real
            if simulated and not include_simulated:
                continue
            config = result.detection.config.model_dump(mode="json") if result.detection else {}
            settings = {
                "config": config,
                "metadata": {
                    key: result.detection.metadata.get(key)
                    for key in (
                        "weights",
                        "model_revision",
                        "model_id",
                        "library_versions",
                        "device",
                        "precision",
                        "batch_size",
                        "preprocessing",
                    )
                }
                if result.detection
                else {},
                "vlm": run.vlm.config.model_dump(
                    mode="json", exclude={"price", "key_env", "name", "config_id"}
                )
                if run.vlm
                else None,
                "image_settings": {
                    k: run.image.get(k) for k in ("longest_edge", "quality", "sent_format")
                },
            }
            settings_hash = hashlib.sha256(
                json.dumps(settings, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()
            identity = (
                result.method,
                result.detector,
                run.mode,
                run.experiment_version,
                run.dataset_split,
                run.task_prompt_sha256,
                run.dictionary_version,
                simulated,
                settings_hash,
            )
            groups[identity].append((run, result))
    summaries = []
    for identity, pairs in groups.items():
        ms = [result_metrics(run, result) for run, result in pairs]
        scored = [m for m in ms if m["scoring_ready"]]
        boxes = [v for m in ms for v in m["ious"]]
        gt_count = sum(m["gt_count"] for m in scored)
        tp = sum(m["tp"] for m in scored)
        pred_count = sum(m["in_scope_prediction_count"] for m in scored)
        timings = defaultdict(list)
        stages = defaultdict(Counter)
        for _, result in pairs:
            for stage, status in result.stages.items():
                stages[stage][status] += 1
            for stage, duration in result.timings.items():
                timings[stage].append(duration)
        summaries.append(
            {
                "method": identity[0],
                "detector": identity[1],
                "mode": identity[2],
                "experiment_version": identity[3],
                "dataset_split": identity[4],
                "task_prompt_sha256": identity[5],
                "dictionary_version": identity[6],
                "simulated": identity[7],
                "settings_sha256": identity[8],
                "tasks": len(pairs),
                "reference_missing": sum(not m["reference_ready"] for m in ms),
                "human_review_missing": sum(not m["scoring_ready"] for m in ms),
                "gt_count_evaluated": gt_count,
                "tp": tp,
                "fp": pred_count - tp,
                "fn": gt_count - tp,
                "recall": tp / gt_count if gt_count else None,
                "precision": tp / pred_count if pred_count else None,
                "paired_count": len(boxes),
                "missing_pairs": sum(m["missing_pairs"] for m in scored),
                "mean_iou": mean(boxes) if boxes else None,
                "median_iou": median(boxes) if boxes else None,
                "subject_auto": _rate(m["subject_correct_auto"] for m in ms),
                "subject_human": _rate(m["subject_correct_human"] for m in ms),
                "candidate_usable": _rate(m["candidate_usable"] for m in ms),
                "query_target_coverage": _coverage(ms, "query_covered_count", "required_gt_count"),
                "query_coverage_by_source": {
                    source: _coverage(
                        [m["query_coverage_by_source"][source] for m in ms],
                        "covered",
                        "denominator",
                    )
                    for source in QUERY_SOURCES
                },
                "fixed_class_support_coverage": _coverage(
                    ms, "supported_gt_count", "required_gt_count"
                ),
                "usable_box_coverage": _coverage(ms, "usable_box_count", "gt_count"),
                "complete_task": _rate(m["complete_task_success"] for m in ms),
                "complete_task_human": _rate(m["complete_task_success_human"] for m in ms),
                "ambiguity": _rate(m["ambiguity_correct"] for m in ms),
                "stages": {k: dict(v) for k, v in stages.items()},
                "timings": {
                    k: {"mean": mean(v), "median": median(v), "max": max(v), "count": len(v)}
                    for k, v in timings.items()
                },
            }
        )
    return summaries


def overall_summary(
    runs: list[DetectorExperiment],
    include_simulated: bool = False,
) -> list[dict]:
    """Availability across every planned method row for requested settings.

    Actual weight/library provenance stays in ``aggregate`` subgroups. This
    summary deliberately includes pending and failed rows even when a worker
    never reached the point where it could report actual model provenance.
    Different task hashes are listed explicitly rather than silently assumed to
    describe the same task. Quality with unfinished references remains unknown.
    """
    groups = defaultdict(list)
    settings_by_key = {}
    for run in runs:
        for result in run.results:
            simulated = run.simulated or not result.real
            if simulated and not include_simulated:
                continue
            detector = next((c for c in run.configs if c.detector == result.detector), None)
            settings = {
                "detector": detector.model_dump(mode="json") if detector else None,
                "vlm": run.vlm.config.model_dump(
                    mode="json", exclude={"price", "key_env", "name", "config_id"}
                )
                if run.vlm
                else None,
                "dictionary_version": run.dictionary_version,
                "image_settings": {
                    k: run.image.get(k) for k in ("longest_edge", "quality", "sent_format")
                },
            }
            requested_hash = hashlib.sha256(
                json.dumps(settings, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()
            key = (
                result.method,
                result.detector,
                run.mode,
                run.experiment_version,
                run.dataset_split,
                simulated,
                requested_hash,
            )
            groups[key].append((run, result))
            settings_by_key[key] = settings
    summaries = []
    for key, pairs in groups.items():
        metrics = [result_metrics(run, result) for run, result in pairs]
        scored = [m for m in metrics if m["scoring_ready"]]
        stages = defaultdict(Counter)
        timings = defaultdict(list)
        for _, result in pairs:
            for stage, status in result.stages.items():
                stages[stage][status] += 1
            for stage, duration in result.timings.items():
                timings[stage].append(duration)
        confirmed_gt = sum(m["gt_count"] or 0 for m in metrics)
        evaluated_gt = sum(m["gt_count"] or 0 for m in scored)
        tp = sum(m["tp"] for m in scored)
        fp = sum(m["fp"] for m in scored)
        fn = sum(m["fn"] for m in scored)
        reference_missing = sum(not m["reference_ready"] for m in metrics)
        unevaluated_tasks = len(metrics) - len(scored)
        tasks = sorted({run.task_prompt_sha256 for run, _ in pairs})
        reviews = [run.evaluations.get(result.result_id, DetectorReview()) for run, result in pairs]
        summaries.append(
            {
                "scope": "all_planned_requested_configuration",
                "actual_provenance_is_separate": True,
                "method": key[0],
                "detector": key[1],
                "mode": key[2],
                "experiment_version": key[3],
                "dataset_split": key[4],
                "simulated": key[5],
                "requested_settings_sha256": key[6],
                "requested_settings": settings_by_key[key],
                "task_prompt_sha256s": tasks,
                "distinct_tasks": len(tasks),
                "tasks": len(pairs),
                "planned_tasks": len(pairs),
                "distinct_attempts": len({run.attempt_id for run, _ in pairs}),
                "distinct_images": len({run.image.get("original_sha256") for run, _ in pairs}),
                "status_counts": dict(Counter(result.status for _, result in pairs)),
                "selection_status_counts": dict(
                    Counter(result.selection.status for _, result in pairs)
                ),
                "partial_coordinate_tasks": sum(
                    result.status == "partial_coordinates"
                    or bool(result.detection and result.detection.status == "partial_coordinates")
                    for _, result in pairs
                ),
                "stages": {stage: dict(statuses) for stage, statuses in stages.items()},
                "reference_ready_tasks": len(metrics) - reference_missing,
                "reference_missing": reference_missing,
                "human_reviewed_tasks": sum(review.reviewed for review in reviews),
                "quality_evaluated_tasks": len(scored),
                "quality_unknown_tasks": unevaluated_tasks,
                "subject_judgeable_tasks": sum(
                    run.reference.main_subject_judgeable and m["reference_ready"]
                    for (run, _), m in zip(pairs, metrics)
                ),
                "human_assisted_tasks": sum(
                    bool(review.human_selected_ids) or review.subject_correct_human is not None
                    for review in reviews
                ),
                "gt_count_confirmed": confirmed_gt,
                "gt_count_evaluated": evaluated_gt,
                "gt_count_unevaluated": confirmed_gt - evaluated_gt,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "recall": tp / evaluated_gt if evaluated_gt and not unevaluated_tasks else None,
                "precision": tp / (tp + fp) if tp + fp and not unevaluated_tasks else None,
                "evaluated_recall": tp / evaluated_gt if evaluated_gt else None,
                "evaluated_precision": tp / (tp + fp) if tp + fp else None,
                "candidate_usable": _rate(m["candidate_usable"] for m in metrics),
                "subject_auto": _rate(m["subject_correct_auto"] for m in metrics),
                "subject_human": _rate(m["subject_correct_human"] for m in metrics),
                "complete_task": _rate(m["complete_task_success"] for m in metrics),
                "complete_task_human": _rate(m["complete_task_success_human"] for m in metrics),
                "ambiguity": _rate(m["ambiguity_correct"] for m in metrics),
                "query_target_coverage": _coverage(
                    metrics, "query_covered_count", "required_gt_count"
                ),
                "query_coverage_by_source": {
                    source: _coverage(
                        [m["query_coverage_by_source"][source] for m in metrics],
                        "covered",
                        "denominator",
                    )
                    for source in QUERY_SOURCES
                },
                "fixed_class_support_coverage": _coverage(
                    metrics, "supported_gt_count", "required_gt_count"
                ),
                "usable_box_coverage": _coverage(metrics, "usable_box_count", "gt_count"),
                "timings": {
                    stage: {
                        "mean": mean(values),
                        "median": median(values),
                        "max": max(values),
                        "count": len(values),
                        "missing": len(pairs) - len(values),
                    }
                    for stage, values in timings.items()
                },
            }
        )
    return summaries


def cost_totals(runs: list[DetectorExperiment]) -> dict:
    """Actual shared VLM bill counted once; local compute remains unknown."""
    currencies = defaultdict(lambda: {"known_amount": 0.0, "known_calls": 0, "unknown_calls": 0})
    seen = set()
    local_runs = 0
    for run in runs:
        local_runs += sum(
            bool(r.detection and r.detection.real and not r.detection.cache_hit)
            for r in run.results
        )
        vlm = run.vlm
        if (
            not vlm
            or not vlm.real
            or vlm.cache_hit
            or vlm.result_id in seen
            or not vlm.attempts
            or all(a.get("request_sent") is False for a in vlm.attempts)
        ):
            continue
        seen.add(vlm.result_id)
        currency = vlm.cost.get("currency", "unknown") if vlm.cost else vlm.config.price.currency
        total = currencies[currency]
        if vlm.cost is None or "amount" not in vlm.cost:
            total["unknown_calls"] += 1
        else:
            total["known_calls"] += 1
            total["known_amount"] += vlm.cost["amount"]
    return {
        "currencies": dict(currencies),
        "shared_vlm_calls": len(seen),
        "local_detector_runs": local_runs,
        "local_compute_cost": None,
    }
