import streamlit as st
from pydantic import ValidationError

from vision_lab_tool.evaluation import result_metrics
from vision_lab_tool.images import overlay
from vision_lab_tool.models import ErrorItem, Evaluation, Reference, VisibleObject

ERROR_TAGS = [
    "场景误判",
    "主体漏检",
    "主体误检",
    "主体选错",
    "光线误判",
    "位置偏移",
    "无依据推断",
    "意图污染",
    "构图动作不可执行",
    "参数/器材冲突",
    "格式错误",
    "调用失败",
]
SCORE_DIMENSIONS = ["事实依据", "目标符合度", "可执行性", "器材可行性"]


def review_reference(reference: Reference, scope: str, image):
    key = lambda suffix: f"review:{scope}:ref:{suffix}"
    with st.expander("人工参考标注（绝不发送给模型）", expanded=True):
        st.caption("未知 / 无法判定请写备注，不勾选可判定标签。主体框为方向修正后 0～1 坐标。")
        annotated = st.checkbox(
            "场景标签可判定（启用标签匹配指标）", reference.scene_annotated, key=key("annotated")
        )
        labels = st.text_input(
            "人工场景标签（逗号分隔）", ",".join(reference.scene_labels), key=key("labels")
        )
        notes = st.text_area("人工参考备注 / 未知条件", reference.notes, key=key("notes"))
        count = st.number_input("人工主体框数量", 0, 20, len(reference.objects), key=key("count"))
        objects = []
        for index in range(count):
            existing = reference.objects[index] if index < len(reference.objects) else None
            label = st.text_input(
                f"参考主体 {index + 1} 标签",
                existing.label if existing else "未知",
                key=key(f"label:{index}"),
            )
            values = existing.bbox if existing and existing.bbox else [0.1, 0.1, 0.9, 0.9]
            cols = st.columns(4)
            box = [
                col.number_input(
                    f"{axis} · 参考 {index + 1}",
                    0.0,
                    1.0,
                    float(value),
                    step=0.01,
                    key=key(f"box:{index}:{axis}"),
                )
                for col, axis, value in zip(cols, ["x_min", "y_min", "x_max", "y_max"], values)
            ]
            try:
                objects.append(
                    VisibleObject(
                        object_id=f"ref{index + 1}", label=label, bbox=box, confidence=None
                    )
                )
            except ValidationError:
                st.error(f"参考框 {index + 1} 倒序或零面积，尚未纳入标注。")
        updated = Reference(
            scene_labels=[x.strip() for x in labels.split(",") if x.strip()],
            scene_annotated=annotated,
            objects=objects,
            notes=notes,
        )
        if image is not None and objects:
            st.image(
                overlay(image, objects), caption="人工参考框实时预览", use_container_width=True
            )
        return updated


def review_result(run, result, display_name):
    evaluation = run.evaluations.get(result.result_id, Evaluation())
    key = lambda suffix: f"review:{run.run_id}:{result.result_id}:{suffix}"
    with st.expander(f"人工评测 · {display_name}", expanded=True):
        reviewed = st.checkbox(
            f"已完成人工评测 · {display_name}", evaluation.reviewed, key=key("reviewed")
        )
        st.caption(
            "评分 1=明显不成立，2=主要问题，3=部分成立，4=基本合理，5=充分合理；"
            "不适用/无法判定不计入均分。格式通过不代表事实正确。"
        )
        scores = {}
        for dimension in SCORE_DIMENSIONS:
            options = ["不适用/无法判定", 1, 2, 3, 4, 5]
            value = evaluation.scores.get(dimension)
            score = st.selectbox(
                f"{dimension} · {display_name}",
                options,
                index=options.index(value) if value is not None else 0,
                key=key(f"score:{dimension}"),
            )
            scores[dimension] = score if isinstance(score, int) else None
        correct = st.text_area(
            f"正确情况说明 · {display_name}", evaluation.correct_notes, key=key("correct")
        )
        existing = {error.tag: error for error in evaluation.errors}
        custom = st.text_input(
            f"自定义错误标签（逗号分隔） · {display_name}",
            ",".join(tag for tag in existing if tag not in ERROR_TAGS),
            key=key("custom"),
        )
        options = list(
            dict.fromkeys(
                ERROR_TAGS + [x.strip() for x in custom.split(",") if x.strip()] + list(existing)
            )
        )
        tags = st.multiselect(
            f"错误标签 · {display_name}", options, default=list(existing), key=key("tags")
        )
        errors = []
        for tag in tags:
            error = existing.get(tag, ErrorItem(tag=tag))
            st.markdown(f"**{tag}**")
            conclusion = st.text_area(
                "模型结论", error.model_conclusion, key=key(f"{tag}:conclusion")
            )
            confirmation = st.text_input(
                "人工确认情况", error.human_confirmation, key=key(f"{tag}:confirmation")
            )
            severity_options = ["无法判定", "轻微", "中等", "严重"]
            severity = st.selectbox(
                "严重程度",
                severity_options,
                index=severity_options.index(error.severity),
                key=key(f"{tag}:severity"),
            )
            evidence = st.text_area("证据说明", error.evidence, key=key(f"{tag}:evidence"))
            cause = st.text_area(
                "疑似原因（尚未验证）", error.suspected_cause, key=key(f"{tag}:cause")
            )
            errors.append(
                ErrorItem(
                    tag=tag,
                    model_conclusion=conclusion,
                    human_confirmation=confirmation,
                    severity=severity,
                    evidence=evidence,
                    suspected_cause=cause,
                )
            )
        matches = {}
        obs = result.parsed
        if obs and run.mode == "advice":
            obs = obs["observation"]
        if obs and run.reference.objects:
            st.caption("框 IoU 仅按你明确指定的一对一关系计算。不同主体请选“不配对”。")
            used = set()
            for obj in obs["objects"]:
                if obj["bbox"] is None:
                    continue
                refs = {ref.object_id: ref.label for ref in run.reference.objects}
                options = ["不配对"] + list(refs)
                previous = evaluation.box_matches.get(obj["object_id"], "不配对")
                chosen = st.selectbox(
                    f"{obj['object_id']} · {obj['label']} 对应参考框",
                    options,
                    index=options.index(previous) if previous in options else 0,
                    format_func=lambda rid, refs=refs: (
                        f"{rid}: {refs[rid]}" if rid in refs else rid
                    ),
                    key=key("match:" + obj["object_id"]),
                )
                if chosen != "不配对":
                    if chosen in used:
                        st.error("同一个参考框不能重复配对，此配对未计入。")
                    else:
                        matches[obj["object_id"]] = chosen
                        used.add(chosen)
        run.evaluations[result.result_id] = Evaluation(
            reviewed=reviewed,
            scores=scores,
            errors=errors,
            correct_notes=correct,
            box_matches=matches,
        )
        st.json(result_metrics(run, result), expanded=False)
