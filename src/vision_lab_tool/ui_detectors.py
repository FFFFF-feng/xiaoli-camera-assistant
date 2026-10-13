"""Detector experiment UI. Inference is restricted to the explicit run action."""
from __future__ import annotations

import io
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw
from pydantic import ValidationError

from vision_lab_tool.detector_evaluation import (
    aggregate,
    overall_summary,
    result_metrics,
    validate_review,
)
from vision_lab_tool.detector_models import (
    DetectorConfig,
    DetectorError,
    DetectorExperiment,
    DetectorReference,
    DetectorReview,
    GroundTruth,
)
from vision_lab_tool.detector_reference import (
    apply_reference_edit,
    confirm_pairing,
    confirm_reference_objects,
    initialize_reference_workflow,
)
from vision_lab_tool.detector_runner import (
    BASELINE_PROMPT_VERSION,
    CANDIDATE_PROMPT_VERSION,
    SCOPE_PROMPT_VERSION,
    run_experiment,
)
from vision_lab_tool.detector_storage import DetectorStore, export_csv, export_json
from vision_lab_tool.detectors.client import readiness, stop_worker
from vision_lab_tool.images import overlay, prepare_image
from vision_lab_tool.models import ModelConfig, VisibleObject
from vision_lab_tool.security import scrub

ROOT = Path(__file__).resolve().parents[2]
DETECTORS = {"grounding_dino": "Grounding DINO Tiny", "yolo26": "YOLO26n"}
CASES = [
    "valid", "empty", "duplicate_id", "invalid_box", "ambiguous", "overlap",
    "unsupported", "vlm_network", "vlm_json", "vlm_semantic", "vlm_invalid_box",
]
LEVELS = ["whole", "part", "instance", "region", "combination", "unknown"]
ENTITIES = ["physical", "reflection", "depiction", "mannequin", "scale_model", "unknown"]
PROMPT_OPTIONS = {
    BASELINE_PROMPT_VERSION: "v0 · 原始基线",
    CANDIDATE_PROMPT_VERSION: "v1 · JSON 实例与坐标格式",
    SCOPE_PROMPT_VERSION: "v2 · 任务覆盖与整体、部件层级",
}
ERROR_TAGS = [
    "查询遗漏", "层级错配", "检测漏检", "检测误检", "实体归属错误", "主体关联错误",
    "边缘覆盖不足", "框格式错误", "网络失败", "语义缺失", "未支持类别", "主体歧义",
]


@dataclass
class DetectorJob:
    cancel: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    thread: threading.Thread | None = None
    snapshot: DetectorExperiment | None = None
    result: DetectorExperiment | None = None
    error: str | None = None
    persistence_errors: list[str] = field(default_factory=list)
    done: bool = False


def _demo_bytes():
    image = Image.new("RGB", (800, 500), "#e3eadb")
    ImageDraw.Draw(image).rectangle((160, 75, 560, 425), fill="#c6683f")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _visible(objects):
    return [
        VisibleObject(
            object_id=getattr(obj, "object_id", getattr(obj, "gt_id", "")),
            label=getattr(obj, "label_display", getattr(obj, "label", "")),
            bbox=obj.bbox,
            confidence=None,
        )
        for obj in objects
    ]


def _data_editor(rows, columns, key, config=None, disabled=None):
    # Explicit columns keep the empty editor usable; dynamic rows impose no object limit.
    # Keep the original table stable: applying added_rows to a newly mutated base
    # would add the same annotation again on subsequent Streamlit renders.
    base_key = "det-editor-base:" + key
    if base_key not in st.session_state:
        st.session_state[base_key] = pd.DataFrame(rows, columns=columns)
    return st.data_editor(
        st.session_state[base_key], key=key, num_rows="dynamic", hide_index=True,
        use_container_width=True, column_config=config or {},
        disabled=disabled or [],
    ).to_dict("records")


def _reference_editor(run, image):
    reference, scope = run.reference, run.run_id
    workflow = initialize_reference_workflow(run)
    with st.expander("人工参考框（不进入推理）", expanded=True):
        st.caption(
            "在末行增加任意数量参考框。坐标为方向修正图的 0～1 xyxy；"
            "label 填英文类别（例如 person），AI 预标注必须逐框人工确认。"
            "target_level 区分整体、部件与实例。"
        )
        with st.expander("批量导入 / 编辑参考 JSON"):
            reference_json = st.text_area(
                "参考框 JSON", reference.model_dump_json(indent=2),
                key=f"det-ref:{scope}:json", height=200,
            )
            if st.button("应用参考 JSON", key=f"det-ref:{scope}:import"):
                try:
                    reference = apply_reference_edit(
                        run, DetectorReference.model_validate_json(reference_json),
                    )
                    for suffix in ["objects", "complete", "judgeable", "ambiguous", "boundary", "notes"]:
                        st.session_state.pop(f"det-ref:{scope}:{suffix}", None)
                    st.session_state.pop(f"det-editor-base:det-ref:{scope}:objects", None)
                    st.success("参考 JSON 已通过校验；尚未请求任何模型。")
                except (ValueError, ValidationError) as exc:
                    st.error(f"参考 JSON 不合法，保留有效标注：{exc}")
        columns = ["gt_id", "label", "x_min", "y_min", "x_max", "y_max"] + [
            field_name for field_name in GroundTruth.model_fields
            if field_name not in {"gt_id", "label", "bbox"}
        ]
        rows = []
        for obj in reference.objects:
            row = obj.model_dump(exclude={"bbox"})
            row.update(dict(zip(["x_min", "y_min", "x_max", "y_max"], obj.bbox)))
            rows.append(row)
        options = {
            "target_level": st.column_config.SelectboxColumn(options=LEVELS),
            "entity_kind": st.column_config.SelectboxColumn(options=ENTITIES),
        }
        for name in ["x_min", "y_min", "x_max", "y_max"]:
            options[name] = st.column_config.NumberColumn(min_value=0., max_value=1., step=.01)
        for name in [
            "user_main_subject", "required", "occluded", "truncated", "judgeable",
            "ignore", "out_of_scope", "confirmed",
        ]:
            options[name] = st.column_config.CheckboxColumn()
        edited = _data_editor(
            rows, columns, f"det-ref:{scope}:objects", options,
            disabled=["confirmed", "annotation_source"],
        )
        complete = st.checkbox(
            "人工参考完整且逐框已确认", reference.complete, key=f"det-ref:{scope}:complete"
        )
        judgeable = st.checkbox(
            "用户主目标可判定", reference.main_subject_judgeable,
            key=f"det-ref:{scope}:judgeable",
        )
        ambiguous = st.checkbox(
            "任务允许歧义 / 应当弃权", reference.ambiguity_expected,
            key=f"det-ref:{scope}:ambiguous",
        )
        boundary = st.checkbox(
            "需要检查边缘覆盖", reference.boundary_required, key=f"det-ref:{scope}:boundary"
        )
        notes = st.text_area(
            "检测人工参考备注", reference.notes, key=f"det-ref:{scope}:notes"
        )
        try:
            objects = []
            for row in edited:
                clean = {k: v for k, v in row.items() if pd.notna(v) and v != ""}
                if not clean:
                    continue
                clean["bbox"] = [clean.pop(k) for k in ["x_min", "y_min", "x_max", "y_max"]]
                objects.append(GroundTruth.model_validate(clean))
            updated = DetectorReference(
                complete=False, objects=objects, notes=notes,
                main_subject_judgeable=judgeable, ambiguity_expected=ambiguous,
                boundary_required=boundary, annotation_policy=reference.annotation_policy,
            )
            updated.complete = complete
            updated = apply_reference_edit(run, updated)
            if complete and not updated.complete:
                st.warning("仍有未确认对象；原任务保持部分确认，质量指标继续未评测。")
        except (ValidationError, KeyError, TypeError, ValueError) as exc:
            st.error(f"人工标注尚未合法，保留上次有效标注：{exc}")
            updated = reference
        st.caption(
            f"参考版本 {workflow['reference_version']} · 库存 {len(workflow['inventory_gt_ids'])} 项；"
            "JSON 与表格只编辑草稿。以下按钮明确确认所选对象存在、身份、边界及当前字段。"
        )
        confirm_ids = st.multiselect(
            "本次明确确认的参考 ID", [obj.gt_id for obj in updated.objects],
            key=f"det-ref:{scope}:confirm-ids",
        )
        user_text = st.text_area("人工确认原文", key=f"det-ref:{scope}:user-text")
        revision_reason = st.text_input("参考修订理由", key=f"det-ref:{scope}:reason")
        if st.button("确认所选对象与边界", key=f"det-ref:{scope}:confirm"):
            try:
                run.reference = updated
                updated = confirm_reference_objects(run, confirm_ids, user_text, revision_reason)
                st.session_state.pop(f"det-ref:{scope}:objects", None)
                st.session_state.pop(f"det-editor-base:det-ref:{scope}:objects", None)
                st.success("所选对象已记录人工原文与来源；其他对象保持待定。")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if image is not None and updated.objects:
            st.image(
                overlay(image, _visible(updated.objects)), caption="人工参考框",
                use_container_width=True,
            )
        return updated


def _correctness(label, value, key):
    values = {"未判定": None, "正确": True, "错误": False}
    selected = st.selectbox(
        label, list(values), index=list(values.values()).index(value), key=key
    )
    return values[selected]


def _review_editor(run, result):
    review = run.evaluations.get(result.result_id, DetectorReview())
    scope = f"det-review:{run.run_id}:{result.result_id}"
    name = result.method if result.method != "detector_only" else DETECTORS.get(
        result.detector, result.detector
    )
    with st.expander(f"人工评测 · {name}"):
        reviewed = st.checkbox(
            f"已完成人工评测 · {name}", review.reviewed, key=scope + ":reviewed"
        )
        pred_ids = [obj.object_id for obj in result.candidates]
        st.caption("人工点选作为独立辅助条件保存；不改写自动主体选择。")
        human = st.multiselect(
            f"人工辅助主体 ID · {name}", pred_ids,
            default=[pid for pid in review.human_selected_ids if pid in pred_ids],
            key=scope + ":human",
        )
        automatic_correct = _correctness(
            f"自动主体是否正确 · {name}", review.subject_correct_auto, scope + ":auto"
        )
        human_correct = _correctness(
            f"人工辅助主体是否正确 · {name}", review.subject_correct_human, scope + ":correct"
        )
        st.caption("IoU 仅使用人工明确指定的合法一对一配对；不同类别或层级不计 TP。")
        gt_ids = [obj.gt_id for obj in run.reference.objects]
        matches, used = {}, set()
        for obj in result.candidates:
            options = ["不配对"] + gt_ids
            previous = review.box_matches.get(obj.object_id, "不配对")
            target = st.selectbox(
                f"{name} · {obj.object_id} ({obj.label_display}) 对应参考框", options,
                index=options.index(previous) if previous in options else 0,
                key=scope + ":match:" + obj.object_id,
            )
            if target != "不配对":
                if target in used:
                    st.error("参考框已配对；此重复关系不纳入评测。")
                else:
                    matches[obj.object_id] = target
                    used.add(target)
        with st.expander(f"覆盖与评测范围 · {name}"):
            query_checked = st.checkbox(
                "已人工核对查询覆盖", review.query_covered_gt_ids is not None,
                key=scope + ":query-checked",
            )
            query_gt = st.multiselect(
                "查询覆盖的参考 ID", gt_ids,
                default=[gid for gid in review.query_covered_gt_ids or [] if gid in gt_ids],
                key=scope + ":query-gt",
            )
            source_coverage = {}
            for source in ["from_task", "from_vlm", "fallback", "manual", "merged"]:
                source_checked = st.checkbox(
                    f"已人工核对查询来源：{source}",
                    source in review.query_covered_gt_ids_by_source,
                    key=scope + ":source-checked:" + source,
                )
                source_gt = st.multiselect(
                    f"{source} 覆盖的参考 ID", gt_ids,
                    default=[
                        gid for gid in review.query_covered_gt_ids_by_source.get(source, [])
                        if gid in gt_ids
                    ], key=scope + ":source-gt:" + source,
                )
                if source_checked:
                    source_coverage[source] = source_gt
            support_checked = st.checkbox(
                "已人工核对固定类别支持", review.support_gt_ids is not None,
                key=scope + ":support-checked",
            )
            support_gt = st.multiselect(
                "固定类别支持的参考 ID", gt_ids,
                default=[gid for gid in review.support_gt_ids or [] if gid in gt_ids],
                key=scope + ":support-gt",
            )
            custom_scope = st.checkbox(
                "显式指定任务范围内预测", review.in_scope_pred_ids is not None,
                key=scope + ":scope-checked",
            )
            scoped = st.multiselect(
                "任务范围内预测 ID", pred_ids,
                default=[pid for pid in review.in_scope_pred_ids or [] if pid in pred_ids],
                key=scope + ":scope-pred",
            )
            ignored = st.multiselect(
                "人工 ignore 的预测 ID", pred_ids,
                default=[pid for pid in review.ignored_pred_ids if pid in pred_ids],
                key=scope + ":ignore-pred",
            )
            edge = _correctness("边缘覆盖是否保留", review.edge_preserved, scope + ":edge")
        st.caption("错误清单可增加同类别的多个独立条目；建议标签：" + "、".join(ERROR_TAGS))
        with st.expander(f"批量导入 / 编辑错误 JSON · {name}"):
            errors_json = st.text_area(
                f"错误条目 JSON · {name}",
                json.dumps([error.model_dump() for error in review.errors], ensure_ascii=False, indent=2),
                key=scope + ":errors-json", height=160,
            )
            if st.button(f"应用错误 JSON · {name}", key=scope + ":import-errors"):
                try:
                    parsed_errors = json.loads(errors_json)
                    if not isinstance(parsed_errors, list):
                        raise TypeError("错误清单必须是 JSON 数组")
                    errors = [DetectorError.model_validate(row) for row in parsed_errors]
                    if len({error.error_id for error in errors}) != len(errors):
                        raise ValueError("错误条目 ID 必须唯一")
                    review = review.model_copy(update={"errors": errors})
                    st.session_state.pop(scope + ":errors", None)
                    st.session_state.pop("det-editor-base:" + scope + ":errors", None)
                    st.success("错误清单已校验；同类别条目分别保存。")
                except (ValueError, TypeError, ValidationError) as exc:
                    st.error(f"错误 JSON 不合法，保留有效清单：{exc}")
        error_rows = _data_editor(
            [error.model_dump() for error in review.errors], list(DetectorError.model_fields),
            scope + ":errors", {"confirmed": st.column_config.CheckboxColumn()},
        )
        notes = st.text_area(f"人工评测备注 · {name}", review.notes, key=scope + ":notes")
        try:
            errors = []
            for index, row in enumerate(error_rows):
                clean = {k: v for k, v in row.items() if pd.notna(v) and v != ""}
                if not clean:
                    continue
                if not clean.get("error_id"):
                    id_key = scope + f":error-id:{index}"
                    if id_key not in st.session_state:
                        st.session_state[id_key] = uuid4().hex
                    clean["error_id"] = st.session_state[id_key]
                errors.append(DetectorError.model_validate(clean))
            if len({error.error_id for error in errors}) != len(errors):
                raise ValueError("错误条目 ID 必须唯一")
            updated = DetectorReview(
                reviewed=reviewed, box_matches=matches, human_selected_ids=human,
                subject_correct_auto=automatic_correct, subject_correct_human=human_correct,
                query_covered_gt_ids=query_gt if query_checked else None,
                query_covered_gt_ids_by_source=source_coverage,
                support_gt_ids=support_gt if support_checked else None,
                in_scope_pred_ids=scoped if custom_scope else None, ignored_pred_ids=ignored,
                edge_preserved=edge, errors=errors, notes=notes,
            )
            validate_review(run, result, updated)
            run.evaluations[result.result_id] = updated
        except (ValidationError, ValueError, TypeError) as exc:
            st.error(f"错误清单尚未合法，保留上次有效评测：{exc}")
        pair_text = st.text_area(f"配对确认原文 · {name}", key=scope + ":pair-text")
        pair_reason = st.text_input(f"配对修订理由 · {name}", key=scope + ":pair-reason")
        if st.button(f"确认当前配对与评测范围 · {name}", key=scope + ":confirm-pair"):
            try:
                confirm_pairing(
                    run, result, run.evaluations.get(result.result_id, review),
                    pair_text, pair_reason,
                )
                st.success("当前合法一对一配对与评测范围已人工确认。")
            except ValueError as exc:
                st.error(str(exc))
        st.json(result_metrics(run, result), expanded=False)


def _method_panel(run, result, image, secrets):
    label = result.method if result.method != "detector_only" else DETECTORS.get(
        result.detector, result.detector
    )
    st.subheader(label)
    st.write(f"状态：{result.status} · 自动主体：{result.selection.status}")
    st.write("自动选择 ID：", result.selection.selected_ids or "无（弃权 / 未支持 / 歧义）")
    st.text(result.selection.reason)
    if result.detection and result.detection.cache_hit:
        st.info("检测结果复用缓存，来源 result_id：" + str(result.detection.cache_source))
    if image is not None:
        st.image(
            overlay(image, _visible(result.candidates)), caption=f"{label} 独立候选叠框",
            use_container_width=True,
        )
    st.dataframe(
        [
            {
                "ID": obj.object_id, "原始标签": obj.label_original,
                "显示标签": obj.label_display, "类别 ID": obj.class_id,
                "分数": obj.score, "分数类型": obj.score_kind,
                "层级": obj.target_level, "实体": obj.entity_kind,
                "xyxy": obj.bbox, "主体框占比":
                (obj.bbox[2] - obj.bbox[0]) * (obj.bbox[3] - obj.bbox[1]),
            }
            for obj in result.candidates
        ], use_container_width=True,
    )
    with st.expander(f"原始候选、查询来源、转换和诊断 · {label}"):
        st.json(scrub(result.model_dump(mode="json"), secrets), expanded=False)
    _review_editor(run, result)


def _history(store, current, secrets):
    st.divider()
    st.subheader("检测实验历史与导出")
    saved = store.list_runs()
    if store.load_errors:
        st.warning("检测历史读取异常：" + "; ".join(store.load_errors))
    if saved:
        selected = st.selectbox(
            "选择检测历史", [run.run_id for run in saved],
            format_func=lambda rid: next(
                f"{run.created_at[:19]} · {'模拟' if run.simulated else '真实'} · "
                f"{run.mode} · {run.experiment_version} · "
                f"关联 {run.provenance.get('offline_replay', {}).get('association_rule_version', '原规则')} · "
                f"参考v{run.provenance.get('reference_workflow', {}).get('reference_version', '旧')} · "
                f"{rid[:8]}" for run in saved if run.run_id == rid
            ), key="detector_history_id",
        )
        if st.button("重新打开检测历史", key="detector_history_open"):
            run = store.load_run(selected)
            for key in list(st.session_state):
                if key.startswith((
                    f"det-review:{run.run_id}:", f"det-ref:{run.run_id}:",
                    f"det-editor-base:det-review:{run.run_id}:",
                    f"det-editor-base:det-ref:{run.run_id}:",
                )):
                    del st.session_state[key]
            st.session_state.detector_active_run = run
            st.session_state.detector_memory_runs[run.run_id] = run
            st.rerun()
    records = {run.run_id: run for run in saved}
    records.update(st.session_state.detector_memory_runs)
    if current:
        records[current.run_id] = current
    if not records:
        st.caption("新实验使用独立 detector-1 记录；不会改写四轮 v1 历史。")
        return
    runs = list(records.values())
    cols = st.columns(3)
    reality = cols[0].multiselect("筛选：真实 / 模拟", ["真实", "模拟"], key="det-filter-real")
    splits = cols[1].multiselect("筛选：开发 / 验证", ["开发", "验证"], key="det-filter-split")
    confirmed = cols[2].selectbox(
        "筛选：人工确认", ["全部", "已完成人工评测", "待评测"], key="det-filter-review"
    )
    cols = st.columns(3)
    methods = cols[0].multiselect(
        "筛选：方法", sorted({r.method for run in runs for r in run.results}),
        key="det-filter-method",
    )
    models = cols[1].multiselect(
        "筛选：模型 / 检测器", sorted({
            value for run in runs for result in run.results
            for value in _model_filters(run, result)
        }),
        key="det-filter-model",
    )
    statuses = cols[2].multiselect(
        "筛选：阶段状态", sorted({
            value for run in runs for result in run.results
            for value in [result.status, *result.stages.values()]
        }),
        key="det-filter-status",
    )
    stages = st.multiselect(
        "筛选：阶段", sorted({stage for run in runs for result in run.results for stage in result.stages}),
        key="det-filter-stage",
    )
    cols = st.columns(3)
    tasks = cols[0].multiselect(
        "筛选：共同任务", sorted({run.task_prompt for run in runs}), key="det-filter-task"
    )
    hashes = cols[1].multiselect(
        "筛选：图片", sorted({run.image["original_sha256"] for run in runs}),
        format_func=lambda value: value[:12], key="det-filter-image",
    )
    tags = cols[2].multiselect(
        "筛选：错误类型", sorted(set(ERROR_TAGS + [
            error.tag for run in runs for review in run.evaluations.values()
            for error in review.errors
        ])), key="det-filter-error",
    )
    filtered = []
    for run in runs:
        if (
            (reality and ("模拟" if run.simulated else "真实") not in reality)
            or (splits and run.dataset_split not in splits)
            or (tasks and run.task_prompt not in tasks)
            or (hashes and run.image["original_sha256"] not in hashes)
        ):
            continue
        chosen = []
        for result in run.results:
            review = run.evaluations.get(result.result_id, DetectorReview())
            if (
                (methods and result.method not in methods)
                or (models and not set(models).intersection(_model_filters(run, result)))
                or (stages and not set(stages).intersection(result.stages))
                or (
                    statuses and not set(statuses).intersection([
                        result.status, *[
                            status for stage, status in result.stages.items()
                            if not stages or stage in stages
                        ],
                    ])
                )
                or (confirmed == "已完成人工评测" and not review.reviewed)
                or (confirmed == "待评测" and review.reviewed)
                or (tags and not any(error.tag in tags for error in review.errors))
            ):
                continue
            chosen.append(result)
        if chosen:
            clone = run.model_copy(deep=True)
            clone.results = chosen
            clone.evaluations = {
                result.result_id: run.evaluations[result.result_id]
                for result in chosen if result.result_id in run.evaluations
            }
            filtered.append(clone)
    st.caption(f"筛选后 {len(filtered)} 条保存记录。自动主体与人工辅助、真实与模拟分别统计。")
    derived_count = sum(bool(run.provenance.get("offline_replay")
                             or run.provenance.get("annotation_only")) for run in filtered)
    if derived_count:
        st.caption(
            f"其中 {derived_count} 条是离线派生或标注版本，不是新增模型请求或独立图片样本。"
            "以下汇总反映保存记录状态；同源新旧规则比较请使用离线对照报告。"
        )
    cols = st.columns(2)
    streamlit_version = tuple(map(int, st.__version__.split(".")[:2]))
    download_action = "ignore" if streamlit_version >= (1, 43) else None
    json_data = lambda: export_json(filtered, secrets)
    csv_data = lambda: export_csv(filtered, secrets)
    # Deferred data is verified against the installed 1.65 API. Older supported
    # Streamlit versions retain their existing bytes contract.
    if streamlit_version < (1, 65):
        json_data, csv_data = json_data(), csv_data()
    cols[0].download_button(
        "下载检测 JSON", json_data, "detector-experiments.json",
        "application/json", on_click=download_action, key="det-export-json",
    )
    cols[1].download_button(
        "下载检测 CSV", csv_data, "detector-experiments.csv",
        "text/csv", on_click=download_action, key="det-export-csv",
    )
    st.caption(
        "IoU 只代表已指定配对框；无参考保持未评测。空框、调用失败、未支持和弃权"
        "保留在总体分母中。单次运行中的候选 ID 不用于跨实验自动关联。"
    )
    with st.expander("真实检测 / 联合定位汇总", expanded=True):
        st.caption("总体统计保留全部计划阶段，包括未执行、缺环境和失败；不同共同任务数量单列。")
        st.json(overall_summary([run for run in filtered if not run.simulated]), expanded=False)
        st.caption("以下按实际权重与依赖来源分组，不能用成功子组代替总体可用率。")
        st.json(aggregate([run for run in filtered if not run.simulated]), expanded=False)
    with st.expander("模拟流程汇总（与图片内容无关）"):
        st.json(overall_summary([run for run in filtered if run.simulated],
                                include_simulated=True), expanded=False)
        st.json(
            aggregate([run for run in filtered if run.simulated], include_simulated=True),
            expanded=False,
        )


def _model_filters(run, result):
    identities = [result.detector] if result.detector else []
    if run.vlm:
        identities.append(f"{run.vlm.config.name} · {run.vlm.config.model_id}")
    return identities or ["未配置 VLM"]


def _start_job(store, image, secrets, kwargs):
    job = DetectorJob()

    def on_stage(snapshot, *_args, **_kwargs):
        if not isinstance(snapshot, DetectorExperiment):
            return
        clone = snapshot.model_copy(deep=True)
        with job.lock:
            job.snapshot = clone
        try:
            store.save_run(clone, secrets)
        except OSError as exc:
            with job.lock:
                job.persistence_errors.append(str(scrub(str(exc), secrets)))

    def execute():
        try:
            result = run_experiment(image, **kwargs, on_stage=on_stage, cancel_event=job.cancel)
            with job.lock:
                job.result = result
            try:
                store.save_run(result, secrets)
            except OSError as exc:
                with job.lock:
                    job.persistence_errors.append(str(scrub(str(exc), secrets)))
        except Exception as exc:  # noqa: BLE001 -- preserve independent completed stages
            with job.lock:
                job.error = str(scrub(str(exc), secrets))
                if job.snapshot:
                    job.result = job.snapshot.model_copy(deep=True)
                    job.result.stages["run"] = "ui_stage_error"
            if job.result:
                try:
                    store.save_run(job.result, secrets)
                except OSError as save_error:
                    with job.lock:
                        job.persistence_errors.append(str(scrub(str(save_error), secrets)))
        finally:
            with job.lock:
                job.done = True

    job.thread = threading.Thread(target=execute, daemon=True, name="detector-experiment")
    st.session_state.detector_job = job
    st.session_state.detector_job_image = image
    job.thread.start()


def _poll_job():
    job = st.session_state.get("detector_job")
    if job is None:
        return
    with job.lock:
        done, result, error = job.done, job.result, job.error
        snapshot = job.snapshot.model_copy(deep=True) if job.snapshot else None
        persistence_errors = job.persistence_errors.copy()
    st.write("运行阶段：", snapshot.stages if snapshot else {"startup": "running"})
    if not done:
        if st.button("取消当前检测任务", key="detector_cancel"):
            job.cancel.set()
            stop_worker()
            st.warning("已请求取消；保留已完成阶段。")
        st.caption("后台执行，可取消；每个阶段完成后保存，未完成结果不评分。")
        return
    if error:
        st.session_state.detector_last_job_error = error
    if persistence_errors:
        st.session_state.detector_persistence_error = persistence_errors[-1]
    if result is not None:
        st.session_state.detector_active_run = result
        st.session_state.detector_memory_runs[result.run_id] = result
        st.session_state.detector_run_images[result.run_id] = st.session_state.detector_job_image
    st.session_state.detector_job = None
    st.rerun()


def render_detector_page(store_root: Path, configs: list[ModelConfig], keys: dict, secret_values: list):
    store = DetectorStore(store_root)
    for key, value in [
        ("detector_active_run", None), ("detector_memory_runs", {}),
        ("detector_run_images", {}), ("detector_cache", {}), ("detector_job", None),
    ]:
        if key not in st.session_state:
            st.session_state[key] = value
    st.header("检测与联合定位")
    st.caption(
        "纯检测无需视觉模型和 API Key；定位对照的 A / B1 / B2 共用一次 VLM 回答。"
        "点击运行才推理，标注、下载与重开均不调用模型。"
    )
    mode_label = st.radio("检测实验入口", ["纯检测", "定位对照"], key="detector_mode")
    mode = "pure_detection" if mode_label == "纯检测" else "localization"
    simulated = st.checkbox("模拟验证（不联网、不加载权重）", key="detector_simulated")
    case = st.selectbox("模拟夹具", CASES, key="detector_mock_case") if simulated else "valid"
    if simulated:
        st.warning("模拟夹具只验证工具流程，与输入图片内容无关，不是检测质量。")
    selected = st.multiselect(
        "检测器（可只选一个）", list(DETECTORS), default=list(DETECTORS),
        format_func=DETECTORS.get, key="detector_selected",
    )
    vlm_config = None
    prompt_version = None
    if mode == "localization":
        prompt_version = st.selectbox(
            "定位提示词版本", list(PROMPT_OPTIONS),
            index=list(PROMPT_OPTIONS).index(CANDIDATE_PROMPT_VERSION),
            format_func=lambda value: PROMPT_OPTIONS[value] + " · " + value,
            key="detector_prompt_version",
            help="默认为 v0。切换只设置下一次运行；点击运行对照才调用模型，已保存记录保留原版本。",
        )
        if configs:
            default = next((i for i, c in enumerate(configs) if "glm-4.6v" in c.model_id.lower()), 0)
            cid = st.selectbox(
                "联合定位语义基线", [config.config_id for config in configs], index=default,
                format_func=lambda config_id: next(c.name for c in configs if c.config_id == config_id),
                key="detector_vlm",
            )
            vlm_config = next(config for config in configs if config.config_id == cid)
            st.caption("默认 GLM-4.6V 依据接口结构稳定性；不表示识图准确率最高。")
            if not simulated and vlm_config.key_env and not keys.get(cid):
                st.info("所选视觉模型密钥未配置，可在原模型设置中保存；纯检测和模拟无需密钥。")
        else:
            st.warning("暂无 VLM 配置；定位模拟仍可运行。")
            if simulated:
                vlm_config = ModelConfig(name="模拟语义基线", provider="模拟", protocol="mock")
    cols = st.columns(3)
    device = cols[0].selectbox("检测设备", ["cpu", "cuda:0"], key="detector_device")
    version = cols[1].text_input("检测实验版本", "detector-v1", key="detector_version")
    split = cols[2].selectbox("检测数据集用途", ["开发", "验证"], key="detector_split")
    detector_configs = []
    with st.expander("检测阈值、权重与有限超时"):
        st.caption("仅开发图调阈值；验证图保留冻结参数。页面不会安装依赖或下载权重。")
        for detector in selected:
            st.write(DETECTORS[detector])
            path = ROOT / "data" / "vision_lab" / "model_cache" / (
                "grounding-dino-tiny" if detector == "grounding_dino" else "yolo26n.pt"
            )
            weights = st.text_input("本地权重路径", str(path), key=f"det-config:{detector}:weights")
            cols = st.columns(3)
            threshold = cols[0].slider(
                "框阈值" if detector == "grounding_dino" else "confidence 阈值", 0., 1.,
                .35 if detector == "grounding_dino" else .25, .01,
                key=f"det-config:{detector}:threshold",
            )
            text_threshold = cols[1].slider(
                "文字阈值", 0., 1., .25, .01, key=f"det-config:{detector}:text",
                disabled=detector != "grounding_dino",
            )
            timeout = cols[2].number_input(
                "超时（秒）", 1., 600., 180., 10., key=f"det-config:{detector}:timeout"
            )
            imgsz = 640
            if detector == "yolo26":
                imgsz = st.number_input(
                    "YOLO imgsz", 32, 4096, 640, 32, key=f"det-config:{detector}:imgsz",
                )
            else:
                st.caption("Grounding DINO 使用锁定处理器的短边 800 / 长边上限 1333；实际内部尺寸写入记录。")
            config = DetectorConfig(
                detector=detector, weights_path=weights, device=device,
                model_id="IDEA-Research/grounding-dino-tiny" if detector == "grounding_dino" else "yolo26n.pt",
                box_threshold=threshold, confidence=threshold, text_threshold=text_threshold,
                timeout_seconds=timeout, imgsz=imgsz,
            )
            detector_configs.append(config)
            if not simulated:
                st.json(readiness(config), expanded=False)
        if st.button("停止空闲检测 worker", key="detector_stop_worker"):
            stop_worker()
            st.success("已停止检测 worker；下次明确运行会重新加载。")
    with st.expander("共同发送 JPEG 设置"):
        longest = st.slider("检测发送图片最长边", 256, 4096, 1600, 64, key="detector_longest")
        quality = st.slider("检测 JPEG 质量", 20, 100, 88, key="detector_quality")
    upload = st.file_uploader("上传检测照片", type=["jpg", "jpeg", "png"], key="detector_upload")
    if st.button("使用检测内置示例图", key="detector_demo"):
        st.session_state.detector_image_bytes = _demo_bytes()
    content = upload.getvalue() if upload else st.session_state.get("detector_image_bytes")
    prepared = None
    if content:
        try:
            prepared = prepare_image(content, longest, quality)
            st.image(prepared.sent_bytes, caption="本次待发送的统一 JPEG", width=600)
            with st.expander("原始 / 修正 / 发送尺寸与哈希"):
                st.json(prepared.metadata())
        except ValueError as exc:
            st.error(str(exc))
    task = st.text_area("共同定位任务", "找出照片中的人物", key="detector_task")
    manual = ""
    if mode == "pure_detection":
        manual = st.text_area(
            "手工英文查询（每行一个，可留空使用冻结任务词典）", key="detector_manual_queries",
            help="仅 Grounding DINO 使用英文短语。手工查询、共同任务与 VLM 提取分别保存来源。",
        )
    use_cache = st.checkbox("复用兼容缓存（结果注明原来源）", True, key="detector_use_cache")
    st.caption("共同任务与人工真值分别存储；不得从参考框或样例文件名构造查询。")
    busy = st.session_state.detector_job is not None
    if st.button(
        "运行检测" if mode == "pure_detection" else "运行对照", type="primary",
        disabled=prepared is None or not detector_configs or busy or (
            mode == "localization" and vlm_config is None
        ),
        key="detector_run",
    ):
        kwargs = {
            "configs": detector_configs, "mode": mode, "task_prompt": task,
            "vlm_config": vlm_config, "key": keys.get(vlm_config.config_id, "") if vlm_config else "",
            "experiment_version": version, "dataset_split": split,
            "manual_queries": [q.strip() for q in manual.splitlines() if q.strip()],
            "simulated": simulated, "mock_case": case,
            "prompt_version": prompt_version,
            "cache": st.session_state.detector_cache if use_cache else None,
        }
        st.session_state.detector_last_job_error = None
        st.session_state.detector_persistence_error = None
        if simulated:
            # Offline fixtures finish immediately and share the same explicit run boundary.
            try:
                def persist_stage(snapshot, *_args, **_kwargs):
                    if isinstance(snapshot, DetectorExperiment):
                        try:
                            store.save_run(snapshot, secret_values)
                        except OSError as exc:
                            st.session_state.detector_persistence_error = str(scrub(str(exc), secret_values))

                run = run_experiment(prepared, **kwargs, on_stage=persist_stage)
                st.session_state.detector_active_run = run
                st.session_state.detector_memory_runs[run.run_id] = run
                st.session_state.detector_run_images[run.run_id] = prepared
                persist_stage(run)
            except Exception as exc:  # noqa: BLE001 -- display validation and isolated failures
                st.error(str(scrub(str(exc), secret_values)))
        else:
            _start_job(store, prepared, secret_values, kwargs)
    if st.session_state.detector_job is not None:
        fragment = st.fragment(run_every="1s")(_poll_job)
        fragment()
    if st.session_state.get("detector_last_job_error"):
        st.error(st.session_state.detector_last_job_error)
    if st.session_state.get("detector_persistence_error"):
        st.warning(
            "阶段记录写盘失败，运行结果仍保留在当前会话；可下载或重试保存："
            + st.session_state.detector_persistence_error
        )
    active = st.session_state.detector_active_run
    if active:
        st.subheader(f"冻结检测实验 · {active.run_id[:12]}")
        st.caption(
            f"{'模拟' if active.simulated else '真实'} · {active.mode} · {active.experiment_version} · "
            f"{active.dataset_split} · attempt {active.attempt_id[:12]}"
        )
        st.text("本次运行任务：" + active.task_prompt)
        if active.mode == "localization":
            frozen = getattr(active, "provenance", {})
            if frozen:
                frozen_version = frozen.get("localization_prompt_version", "未记录")
                frozen_hash = frozen.get("localization_prompt_sha256", "未记录")
                st.caption(
                    "冻结定位提示词：" + PROMPT_OPTIONS.get(frozen_version, frozen_version)
                    + " · " + frozen_version + " · SHA256 " + frozen_hash
                )
                with st.expander("冻结定位提示词全文与来源"):
                    st.code(str(scrub(frozen.get("localization_prompt", "未记录全文"), secret_values)),
                            language="text")
                    st.json(scrub(frozen, secret_values), expanded=False)
            else:
                st.caption("此历史记录未保存定位提示词来源，原记录保持不变。")
        with st.expander("冻结运行条件、阶段耗时与共享费用"):
            st.json(scrub({
                "image": active.image, "configs": [c.model_dump() for c in active.configs],
                "task_sha256": active.task_prompt_sha256, "dictionary": active.dictionary_version,
                "stages": active.stages, "timings": active.timings, "costs": active.costs,
            }, secret_values), expanded=False)
            st.caption("共享 VLM 费用只计一次；本地计算成本未知。VLM 可信度与检测分数不合并。")
        active_image = st.session_state.detector_run_images.get(active.run_id)
        corrected = active_image.corrected if active_image else None
        if corrected is None and prepared and prepared.original_sha256 == active.image["original_sha256"]:
            corrected = prepared.corrected
            active_image = prepared
        if corrected is None and active.sample_file:
            try:
                corrected = store.load_sample(active)
            except (ValueError, OSError):
                st.warning("历史图片副本无法读取；仍可编辑评测。")
        if corrected is None:
            st.info("未保存照片副本；重新上传相同哈希原图即可显示框。")
        active.reference = _reference_editor(active, corrected)
        if active.vlm:
            if active.vlm.cache_hit:
                st.info("共享 VLM 原答复复用缓存，来源 result_id：" + str(active.vlm.cache_source))
            with st.expander("共享 VLM 原文、解析 / 框 / 语义状态"):
                st.code(str(scrub(active.vlm.raw_answer or "无回答", secret_values)), language="json")
                st.json(scrub(active.vlm.model_dump(mode="json"), secret_values), expanded=False)
        if active.results:
            columns = st.columns(len(active.results))
            for column, result in zip(columns, active.results):
                with column:
                    _method_panel(active, result, corrected, secret_values)
        st.session_state.detector_memory_runs[active.run_id] = active
        save_sample = st.checkbox(
            "主动保存检测照片副本（本地去 EXIF）", key=f"det-save-sample:{active.run_id}"
        )
        if st.button("保存检测记录与评测", key="detector_save"):
            if save_sample and corrected is None:
                st.error("没有照片可保存；请先重传相同原图。")
            else:
                try:
                    derived = store.save_review_version(
                        active, secret_values, prepared=active_image if save_sample else None,
                    )
                    try:
                        st.session_state.detector_memory_runs[active.run_id] = store.load_run(
                            active.run_id,
                        )
                    except (OSError, ValueError):
                        pass
                    st.session_state.detector_active_run = derived
                    st.session_state.detector_memory_runs[derived.run_id] = derived
                    if active_image:
                        st.session_state.detector_run_images[derived.run_id] = active_image
                    st.session_state.detector_history_id = derived.run_id
                    st.rerun()
                except (ValueError, OSError, ValidationError) as exc:
                    st.error(str(scrub("保存失败：" + str(exc), secret_values)))
    _history(store, active, secret_values)
