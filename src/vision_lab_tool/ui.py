from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from PIL import Image, ImageDraw

from vision_lab_tool.configuration import (
    collect_secret_values,
    default_configs,
    ensure_focused_configs,
    focused_configs,
    resolve_key,
)
from vision_lab_tool.credentials import KeyVault
from vision_lab_tool.evaluation import aggregate, cost_totals
from vision_lab_tool.images import overlay, prepare_image
from vision_lab_tool.models import Evaluation, Reference
from vision_lab_tool.presentation import overlay_objects
from vision_lab_tool.prompts import ADVICE_TEMPLATE, RECOGNITION_TEMPLATE
from vision_lab_tool.runner import run_comparison
from vision_lab_tool.storage import Store, export_csv, export_json
from vision_lab_tool.ui_config import edit_configs
from vision_lab_tool.ui_credentials import edit_keys, read_saved_keys
from vision_lab_tool.ui_results import readable_result
from vision_lab_tool.ui_review import ERROR_TAGS, review_reference, review_result

ROOT = Path(__file__).resolve().parents[2]
STATUS = {
    "ok": "结构通过",
    "authentication": "认证失败",
    "permission_region": "地区/权限限制",
    "rate_limit": "限流",
    "timeout": "超时",
    "http_error": "HTTP 错误",
    "truncated": "输出截断",
    "json_parse": "JSON 解析失败",
    "schema_validation": "结构校验失败",
    "network_error": "网络错误",
    "configuration": "配置错误",
    "response_parse": "厂商响应解析失败",
    "refused": "拒绝/未完成",
    "internal_error": "内部错误",
}


def _secrets():
    try:
        return dict(st.secrets)
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return {}


def _demo_image():
    image = Image.new("RGB", (800, 500), "#e3eadb")
    draw = ImageDraw.Draw(image)
    draw.rectangle((160, 75, 560, 425), fill="#c6683f")
    draw.ellipse((280, 160, 440, 320), fill="#ffdf95")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _history(store, current, blind, secret_values):
    st.divider()
    st.subheader("历史记录与导出")
    history = store.list_runs()
    if store.load_errors:
        st.warning("部分历史文件未能读取：" + "; ".join(store.load_errors))
    if history:
        selected = st.selectbox(
            "选择历史记录",
            [r.run_id for r in history],
            format_func=lambda rid: next(
                f"{r.created_at[:19]} · {r.mode} · {r.run_id[:8]}"
                for r in history
                if r.run_id == rid
            ),
        )
        if st.button("重新打开所选历史"):
            run = store.load_run(selected)
            for key in list(st.session_state):
                if key.startswith(f"review:{run.run_id}:"):
                    del st.session_state[key]
            st.session_state.lab_active_run = run
            st.session_state.lab_memory_runs[run.run_id] = run
            st.session_state.lab_history_view = True
            st.rerun()
    candidates = {run.run_id: run for run in history}
    candidates.update(st.session_state.lab_memory_runs)
    if current:
        candidates[current.run_id] = current
    records = list(candidates.values())
    if not records:
        st.caption("保存运行结果后可重新打开；历史重开、筛选和下载均不请求模型。")
        return
    names = sorted({r.config.name for run in records for r in run.results})
    labels = {name: f"模型 {index + 1}" if blind else name for index, name in enumerate(names)}
    cols = st.columns(3)
    models = cols[0].multiselect("导出筛选：模型", names, format_func=labels.get)
    modes = cols[1].multiselect("导出筛选：模式", ["recognition", "advice"])
    splits = cols[2].multiselect("导出筛选：用途", ["开发", "验证"])
    cols = st.columns(3)
    hashes = cols[0].multiselect(
        "导出筛选：图片哈希",
        sorted({r.image["original_sha256"] for r in records}),
        format_func=lambda value: value[:12],
    )
    versions = cols[1].multiselect(
        "导出筛选：实验版本", sorted({r.experiment_version for r in records})
    )
    tags = cols[2].multiselect(
        "导出筛选：错误类型",
        sorted(
            set(
                ERROR_TAGS
                + [e.tag for run in records for ev in run.evaluations.values() for e in ev.errors]
            )
        ),
    )
    filtered = []
    for run in records:
        if (
            (modes and run.mode not in modes)
            or (splits and run.dataset_split not in splits)
            or (hashes and run.image["original_sha256"] not in hashes)
            or (versions and run.experiment_version not in versions)
        ):
            continue
        chosen = [
            result
            for result in run.results
            if (not models or result.config.name in models)
            and (
                not tags
                or any(
                    e.tag in tags
                    for e in run.evaluations.get(
                        result.result_id,
                        Evaluation(),
                    ).errors
                )
            )
        ]
        if chosen:
            clone = run.model_copy(deep=True)
            clone.results = chosen
            clone.evaluations = {
                r.result_id: run.evaluations[r.result_id]
                for r in chosen
                if r.result_id in run.evaluations
            }
            filtered.append(clone)
    st.caption(f"筛选后 {len(filtered)} 次运行；导出保留真实模型身份和完整嵌套字段。")
    cols = st.columns(2)
    download_action = (
        "ignore" if tuple(map(int, st.__version__.split(".")[:2])) >= (1, 43) else None
    )
    cols[0].download_button(
        "下载完整 JSON",
        export_json(filtered, secret_values),
        "vision-lab.json",
        "application/json",
        on_click=download_action,
    )
    cols[1].download_button(
        "下载评测 CSV",
        export_csv(filtered, secret_values),
        "vision-lab.csv",
        "text/csv",
        on_click=download_action,
    )
    st.caption(
        "汇总按配置、模型 ID、模式、实验版本、用途、提示词和请求/预处理设置哈希分组；重复运行不是独立图片样本。"
        "场景为标签集合完全一致 / 已标注且有解析观察的结果数；IoU 仅人工指定框对。"
        "格式/调用率分母为运行结果数；耗时为一次尝试耗时；评分单独计均分与缺失。"
    )
    real_summary = aggregate(filtered)
    if blind:
        real_summary = [
            {
                **row,
                "model_name": labels.get(row["model_name"]),
                "model_id": "已隐藏",
                "config_id": "已隐藏",
            }
            for row in real_summary
        ]
    st.write("真实模型汇总（未验证准确率；模拟不进入此表）")
    if real_summary:
        st.dataframe(real_summary, use_container_width=True)
    else:
        st.info("尚无真实模型评测数据。")
    with st.expander("模拟流程统计（仅验证工具，不是模型质量排行）"):
        simulated = [r for r in aggregate(filtered, include_mock=True) if r["simulated"]]
        if blind:
            simulated = [
                {
                    **row,
                    "model_name": labels.get(row["model_name"]),
                    "model_id": "已隐藏",
                    "config_id": "已隐藏",
                }
                for row in simulated
            ]
        st.dataframe(simulated, use_container_width=True)
    st.write("费用估算按币种累计（未知费用另计，无汇率转换）")
    st.json(cost_totals(filtered), expanded=False)


def main():
    st.set_page_config(page_title="小栗 · 视觉模型测试窗口", page_icon="📷", layout="wide")
    load_dotenv(ROOT / ".env")
    store = Store(Path(os.getenv("VISION_LAB_DATA_DIR", str(ROOT / "data" / "vision_lab"))))
    if "lab_configs" not in st.session_state:
        st.session_state.lab_config_load_failed = False
        try:
            st.session_state.lab_configs = store.load_configs() or default_configs()
        except (ValueError, OSError):
            st.warning("保存配置无法读取，已使用可编辑默认示例。")
            st.session_state.lab_configs = default_configs()
            st.session_state.lab_config_load_failed = True
    previous_count = len(st.session_state.lab_configs)
    st.session_state.lab_configs = ensure_focused_configs(st.session_state.lab_configs)
    presets_added = len(st.session_state.lab_configs) != previous_count
    for key, default in [
        ("lab_active_run", None),
        ("lab_memory_runs", {}),
        ("lab_run_images", {}),
        ("lab_references", {}),
        ("lab_last_input", None),
        ("lab_history_view", False),
        ("lab_selected_ids", None),
        ("lab_profile_selections", {}),
        ("lab_known_secrets", []),
        ("lab_temporary_keys", {}),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default
    secrets = _secrets()
    vault = KeyVault(store.root / "credentials.dpapi.json")
    saved_keys = read_saved_keys(vault)
    st.session_state.lab_saved_keys = saved_keys
    widget_keys = {
        k.removeprefix("temp-key:"): v
        for k, v in st.session_state.items()
        if k.startswith("temp-key:") and isinstance(v, str)
    }
    st.session_state.lab_temporary_keys.update(widget_keys)
    temporary_keys = st.session_state.lab_temporary_keys
    secret_values = collect_secret_values(
        st.session_state.lab_configs, temporary_keys, secrets, saved=saved_keys
    )
    secret_values += [v for k, v in st.session_state.items() if k.startswith("api-input:") and v]
    secret_values = list(dict.fromkeys(secret_values + st.session_state.lab_known_secrets))
    st.session_state.lab_known_secrets = secret_values
    if presets_added and not st.session_state.get("lab_config_load_failed", False):
        # Add the new presets while applying the same redaction as manual config saves.
        store.save_configs(st.session_state.lab_configs, secret_values)
    page = st.sidebar.radio(
        "测试页面", ["四模型视觉测试", "检测与联合定位"], key="lab_page"
    )
    if page == "检测与联合定位":
        from vision_lab_tool.ui_detectors import render_detector_page

        with st.sidebar:
            edit_keys(vault, saved_keys, secrets)
        detector_keys = {
            config.config_id: resolve_key(
                config, temporary_keys.get(config.config_id, ""), secrets, saved=saved_keys
            )
            for config in st.session_state.lab_configs
        }
        render_detector_page(store.root, st.session_state.lab_configs, detector_keys, secret_values)
        return
    st.title("📷 小栗 · 视觉模型测试窗口")
    st.caption("填入 Key → 选择要比较的模型 → 上传照片 → 运行 → 人工评测与保存")
    with st.sidebar:
        st.header("模型与测试设置")
        blind = st.toggle("隐藏模型名称（盲评）", key="lab_blind")
        if not blind:
            edit_keys(vault, saved_keys, secrets)
        profile = st.radio(
            "模型选择方式",
            ["常用四模型", "模拟 / 其他模型"],
            key="lab_profile",
            help="常用四模型已填好连接参数；模拟模式不需要密钥。",
        )
        if not blind:
            with st.expander("高级模型设置（通常不用改）"):
                edit_configs(store, secret_values)
        configs = st.session_state.lab_configs
        by_id = {c.config_id: c for c in configs}
        focused_ids = [c.config_id for c in focused_configs()]
        available_ids = focused_ids if profile == "常用四模型" else list(by_id)
        name_counts = {c.name: sum(x.name == c.name for x in configs) for c in configs}
        display = {
            c.config_id: f"模型 {chr(65 + index)}"
            if blind
            else c.name
            if name_counts[c.name] == 1
            else f"{c.name} · 配置 {index + 1}"
            for index, c in enumerate(configs)
        }
        default = (
            focused_ids
            if profile == "常用四模型"
            else [c.config_id for c in configs if c.protocol == "mock"][:2]
        )
        default = st.session_state.lab_profile_selections.get(profile, default)
        default = [cid for cid in default if cid in available_ids]
        # New Streamlit clients send formatted option labels. Never reuse the same
        # widget identity after changing those labels (e.g. blind mode or renaming).
        label_version = hashlib.sha256((profile + repr(display)).encode("utf-8")).hexdigest()[:16]
        selected = st.multiselect(
            "选择要比较的模型（2～4 个）",
            available_ids,
            default=default,
            format_func=lambda cid: display.get(cid, str(cid)),
            key="lab_selected:" + label_version,
        )
        st.session_state.lab_selected_ids = selected
        st.session_state.lab_profile_selections[profile] = selected
        st.caption("这里选中的模型会分别分析同一张照片；选四个就会得到四份结果。")
        if profile == "常用四模型" and not blind:
            st.caption("连接参数已预填：120秒超时、4096输出上限、按各厂商默认推理设置。")
            st.caption("模型需在服务商账号中开通；价格未核价时显示未知。")
        keys = {}
        for cid in selected:
            config = by_id[cid]
            if config.protocol != "mock":
                temporary = st.session_state.lab_temporary_keys.get(cid, "")
                if profile != "常用四模型" and not blind:
                    temporary = st.text_input(
                        f"临时密钥 · {display[cid]}",
                        value=temporary,
                        type="password",
                        key="temp-key:" + cid,
                    )
                    st.session_state.lab_temporary_keys[cid] = temporary
                keys[cid] = resolve_key(config, temporary, secrets, saved=saved_keys)
                st.caption(
                    "密钥已配置"
                    if keys[cid]
                    else ("无密钥本地服务" if not config.key_env else "密钥尚未配置")
                )
        if any(st.session_state.lab_temporary_keys.get(cid) for cid in selected):
            st.caption("当前有会话临时密钥优先使用；清空临时输入后才会改用本机保存项。")
        mode_name = st.radio(
            "实验模式",
            ["纯识图", "建议测试"],
            key="lab_mode",
            help="纯识图检查看得对不对；建议测试检查根据你的目标，建议是否有用。",
        )
        mode = "recognition" if mode_name == "纯识图" else "advice"
        st.caption(
            "纯识图：例如数清照片里的主体、判断位置和光线。"
            if mode == "recognition"
            else "建议测试：例如输入“我想突出骑行者”，比较各模型怎么建议构图与重新拍摄。"
        )
        with st.expander("图片清晰度（默认即可）"):
            longest_edge = st.slider(
                "发送图片最长边",
                256,
                4096,
                1600,
                64,
                help="等比例缩小，较小的原图不会被放大；更大可能保留更多细节并增加传输量。",
            )
            st.caption("最长边示例：4000×3000 的照片，设为1600后发送1600×1200；比例不变。")
            quality = st.slider(
                "JPEG 质量",
                20,
                100,
                88,
                help="数字越低压缩越明显，数字越高文件通常越大；它不是识别准确率。",
            )
            st.caption(
                "JPEG质量影响压缩与细节，不改变尺寸，也不单独决定图像token费用。比较时固定1600和88。"
            )
        with st.expander("提示词与实验版本（高级）"):
            version = st.text_input("实验版本", "experiment-v1")
            split = st.selectbox("数据集用途", ["开发", "验证"])
            saved_templates = store.load_templates()
            default_template = RECOGNITION_TEMPLATE if mode == "recognition" else ADVICE_TEMPLATE
            saved = saved_templates.get(mode, {})
            template = st.text_area(
                "提示词模板",
                saved.get("text", default_template),
                height=220,
                key="lab_template:" + mode,
            )
            prompt_version = st.text_input(
                "提示词版本", saved.get("version", "prompt-v1"), key="lab_prompt_version:" + mode
            )
            if st.button("保存模板版本"):
                saved_templates[mode] = {
                    "text": template,
                    "version": prompt_version,
                    "sha256": hashlib.sha256(template.encode()).hexdigest(),
                }
                store.save_templates(saved_templates, secret_values)
                st.success("模板已保存，尚未请求模型。")
        context, include_exif = {}, False
        if mode == "advice":
            context["goal"] = st.text_area("共同用户目标")
            context["equipment"] = st.text_area("共同器材事实 / 未知条件")
            context["reference"] = st.text_area("可选固定参考资料（所有模型相同）")
            include_exif = st.checkbox("发送原图 EXIF（仅原始拍摄记录）")
        else:
            st.caption(
                "纯识图只发送图片与分析任务；人工参考、目标、器材、EXIF、知识库与历史回答均不加入。"
            )
        st.caption("默认不重试付费请求。detail / 推理 / JSON 能力随模型变化，默认省略可选参数。")
    upload = st.file_uploader("上传测试照片", type=["jpg", "jpeg", "png"])
    if st.button("使用内置模拟示例图"):
        st.session_state.lab_image_bytes = _demo_image()
    content = upload.getvalue() if upload is not None else st.session_state.get("lab_image_bytes")
    prepared = None
    if content:
        try:
            prepared = prepare_image(content, longest_edge, quality)
        except ValueError as exc:
            st.error(str(exc))
    signature = prepared.metadata()["sent_sha256"] + prepared.original_sha256 if prepared else None
    if signature != st.session_state.lab_last_input:
        st.session_state.lab_last_input = signature
        history = st.session_state.lab_active_run
        restoring_same_image = (
            st.session_state.lab_history_view
            and history is not None
            and prepared is not None
            and prepared.original_sha256 == history.image["original_sha256"]
        )
        if not restoring_same_image:
            st.session_state.lab_active_run = None
            st.session_state.lab_history_view = False
    if prepared:
        cols = st.columns(2)
        cols[0].image(prepared.corrected, caption="方向修正后的原图", use_container_width=True)
        cols[1].image(
            prepared.sent_bytes, caption="本次待发送的统一 JPEG", use_container_width=True
        )
        with st.expander("图片尺寸、格式、压缩与哈希"):
            st.json(prepared.metadata())
        if include_exif:
            st.caption("EXIF 开关已开启：以下是原图拍摄记录。")
            st.json(prepared.exif, expanded=False)
    st.info(
        "点击运行后，照片会发送至所选真实服务；模拟配置不联网。默认不保存照片，"
        "保存标注与下载不会重复调用。厂商内部缩放不可控制。"
    )
    if st.button(
        "运行测试", type="primary", disabled=prepared is None or not 2 <= len(selected) <= 4
    ):
        with st.spinner("正在比较；每个配置仅尝试一次…"):
            run = run_comparison(
                [by_id[cid] for cid in selected],
                prepared,
                mode,
                template,
                context,
                version,
                split,
                prompt_version,
                keys,
                include_exif,
            )
        run.reference = st.session_state.lab_references.get(prepared.original_sha256, Reference())
        st.session_state.lab_active_run = run
        st.session_state.lab_memory_runs[run.run_id] = run
        st.session_state.lab_run_images[run.run_id] = prepared
        st.session_state.lab_history_view = False
    active = st.session_state.lab_active_run
    active_image = None
    if active:
        if active.run_id in st.session_state.lab_run_images:
            active_image = st.session_state.lab_run_images[active.run_id]
        elif prepared and prepared.original_sha256 == active.image["original_sha256"]:
            active_image = prepare_image(
                content, active.image["longest_edge"], active.image["quality"]
            )
        elif active.sample_file:
            try:
                corrected = store.load_sample(active)
                buffer = io.BytesIO()
                corrected.save(buffer, "PNG")
                active_image = prepare_image(
                    buffer.getvalue(), active.image["longest_edge"], active.image["quality"]
                )
            except (ValueError, OSError):
                st.warning("历史图片副本无法读取；记录与评测仍可使用。")
        st.subheader(f"运行结果 · {active.run_id[:12]}")
        st.caption(
            f"{active.mode} · {active.experiment_version} · {active.dataset_split} · "
            f"图片 {active.image['original_sha256'][:12]} · {active.created_at}"
        )
        if active_image is None:
            st.info("这条历史未保存照片；重新上传相同哈希的原图即可恢复框叠加。可先继续文字评测。")
        else:
            st.image(active_image.sent_bytes, caption="这次运行实际发送的 JPEG", width=500)
        with st.expander("完整实验条件 / 提示词"):
            st.json(
                {
                    "image": active.image,
                    "context": active.context,
                    "prompt_version": active.prompt_version,
                    "prompt_sha256": active.prompt_sha256,
                }
            )
            st.code(active.prompt)
        active.reference = review_reference(
            active.reference, active.run_id, active_image.corrected if active_image else None
        )
        st.session_state.lab_references[active.image["original_sha256"]] = active.reference
        st.caption("格式合法不代表事实正确。模拟是固定夹具，与上传照片内容无关。")
        columns = st.columns(len(active.results))
        for index, (col, result) in enumerate(zip(columns, active.results)):
            name = f"模型 {chr(65 + index)}" if blind else result.config.name
            with col:
                st.subheader(name)
                if result.config.protocol == "mock":
                    st.warning("模拟 · 固定测试结果 · 不计真实质量排行")
                st.write(STATUS.get(result.status, result.status))
                if result.error:
                    st.error(result.error)
                st.caption(f"{result.elapsed_seconds:.3f} 秒 · {len(result.attempts)} 次尝试")
                st.write(
                    "费用估算："
                    + (
                        f"{result.cost['amount']:.6f} {result.cost['currency']}"
                        if result.cost
                        else "未知 / 模拟不计费"
                    )
                )
                with st.expander("用量与计费范围"):
                    st.json(result.usage.model_dump())
                    if result.cost:
                        st.json(result.cost)
                    if not blind:
                        st.json(result.config.model_dump())
                        st.write("实际返回模型：", result.actual_model or "未知")
                if result.parsed:
                    readable_result(result.parsed, active.mode)
                    observation = (
                        result.parsed
                        if active.mode == "recognition"
                        else result.parsed["observation"]
                    )
                    if active_image:
                        objects = overlay_objects(observation)
                        st.image(
                            overlay(active_image.corrected, objects),
                            caption="模型框（原图统一坐标）",
                            use_container_width=True,
                        )
                with st.expander("原始回答与 JSON（排查用）"):
                    st.code(result.raw_answer or "无最终回答", language="json")
                    if result.parsed:
                        st.json(result.parsed)
                review_result(active, result, name)
        st.session_state.lab_memory_runs[active.run_id] = active
        save_sample = st.checkbox(
            "主动保存此样例照片到本地（方向修正副本，去 EXIF）", key=f"save-sample:{active.run_id}"
        )
        if st.button("保存记录与评测"):
            if save_sample and active_image is None:
                st.error("没有相同照片可保存；请先重传原图。")
            else:
                if save_sample:
                    store.save_sample(active, active_image)
                store.save_run(active, secret_values)
                st.success("已保存到本地 data/vision_lab，可重开评测，无模型调用。")
    elif prepared:
        reference = st.session_state.lab_references.get(prepared.original_sha256, Reference())
        st.session_state.lab_references[prepared.original_sha256] = review_reference(
            reference, prepared.original_sha256, prepared.corrected
        )
    _history(store, active, blind, secret_values)
