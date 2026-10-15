from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path

import httpx
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent

from camera_assistant.config import Settings
from camera_assistant.models import PhoneProfile, PipelineResult, UserRequest
from camera_assistant.pipeline import CameraAssistantPipeline
from camera_assistant.services.cloud import ModelServiceError
from camera_assistant.services.image_analyzer import ImageValidationError
from camera_assistant.services.phone_knowledge import PHONE_MODE_NAMES

st.set_page_config(
    page_title="小栗取景参谋｜相机参数助手",
    page_icon="📷",
    layout="centered",
    initial_sidebar_state="collapsed",
)

SESSION_SCHEMA_VERSION = 11
PIPELINE_RESOURCE_VERSION = 14


def migrate_session_state() -> None:
    """热重载后丢弃与当前数据模型不兼容的旧页面结果。"""
    if st.session_state.get("schema_version") != SESSION_SCHEMA_VERSION:
        st.session_state.pop("last_result", None)
        st.session_state["schema_version"] = SESSION_SCHEMA_VERSION


def load_css() -> None:
    st.markdown(
        f"<style>{(ROOT / 'assets' / 'style.css').read_text(encoding='utf-8')}</style>",
        unsafe_allow_html=True,
    )


def asset_data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


@st.cache_resource
def build_pipeline(resource_version: int) -> tuple[Settings, CameraAssistantPipeline]:
    """构建主流程；版本参数用于在服务热更新后淘汰旧实例。"""
    del resource_version
    settings = Settings.from_env()
    return settings, CameraAssistantPipeline(settings)


def escaped(value: object) -> str:
    return html.escape(str(value))


def clear_device_result() -> None:
    st.session_state.pop("last_result", None)
    st.session_state["phone_pro_confirm"] = False


def clear_photo_result() -> None:
    st.session_state.pop("last_result", None)


def analyze_with_progress(image_content: bytes, request: UserRequest) -> PipelineResult:
    with st.status("小栗开始分析现场图…", expanded=True) as status:
        if settings.cloud_ready:
            st.write("图片识别和方案生成需要一些时间；下方会显示当前进度。")

        def show_progress(message: str) -> None:
            status.update(label=message)
            st.write(message)

        try:
            result = pipeline.run(image_content, request, on_progress=show_progress)
        except Exception:
            status.update(label="这次分析未完成，请查看下方提示", state="error")
            raise
        status.update(label="分析完成，请到下方查看拍摄方案", state="complete", expanded=False)
        return result


def render_header(settings: Settings) -> None:
    mode = "演示模式" if not settings.cloud_ready else "多模态模式"
    mascot_uri = asset_data_uri(ROOT / "assets" / "camera-red-panda.png")
    st.markdown(
        f"""
        <header class="app-topbar">
          <div class="app-brand"><span class="brand-lens"></span><strong>小栗</strong><small>取景参谋</small></div>
          <div class="mode-badge"><i></i>{escaped(mode)}</div>
        </header>
        <section class="mobile-hero" id="home">
          <div class="mobile-hero-copy">
            <span class="hello-chip">嗨，我是你的摄影搭子</span>
            <h1>拍之前，<br>先问问小栗</h1>
            <p>看懂现场，也看懂你的相机和手机。</p>
            <div class="quick-flow" aria-label="使用流程">
              <span>现场图</span><i></i><span>想要的效果</span><i></i><b>拍摄参数</b>
            </div>
          </div>
          <div class="mobile-mascot">
            <div class="mascot-bubble">交给我吧！</div>
            <img src="{mascot_uri}" alt="拿着相机的小熊猫摄影助手小栗">
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    if not settings.cloud_ready:
        st.markdown(
            """
            <div class="demo-note"><span>体验模式</span>知识检索和机型校验已开启；接入多模态模型后可进一步识别画面。</div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.caption(
            f"视觉模型：{settings.vision_model} · 参数模型：{settings.text_model} · "
            f"定位：{'Grounding DINO' if settings.detector_enabled else '未启用'}"
        )


def localization_overlay(result: PipelineResult) -> Image.Image:
    """在与模型输入同方向、同坐标基准的图像副本上标记候选。"""
    encoded = result.inspection.model_image_data_url.split(",", 1)[1]
    with Image.open(io.BytesIO(base64.b64decode(encoded, validate=True))) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", max(14, image.width // 65))
    except OSError:
        font = ImageFont.load_default()
    for index, candidate in enumerate(result.localization.candidates, start=1):
        x1, y1, x2, y2 = candidate.bbox
        draw.rectangle(
            (x1 * image.width, y1 * image.height, x2 * image.width, y2 * image.height),
            outline="#f57b42",
            width=max(2, image.width // 400),
        )
        # 图中只标编号，完整类别和 ID 在图下展示，避免长标签遮住现场。
        draw.text(
            (x1 * image.width, y1 * image.height),
            str(index),
            font=font,
            fill="#f57b42",
            stroke_width=1,
            stroke_fill="white",
        )
    return image


def render_composition(result: PipelineResult) -> None:
    localization = getattr(result, "localization", None)
    composition = getattr(result, "composition", None)
    if localization is None and composition is None:
        return

    st.subheader("构图与主体位置")
    if localization is not None:
        status_labels = {
            "success": "检测完成",
            "detection_only": "仅获得检测候选",
            "empty": "没有检测到候选",
            "environment_missing": "检测环境尚未准备",
            "model_missing": "检测权重尚未准备",
            "timeout": "检测超时",
            "cancelled": "检测已停止",
            "runtime_error": "检测未完成",
            "partial_coordinates": "部分候选坐标有问题",
            "coordinate_error": "候选坐标有问题",
            "query_missing": "没有可用于定位的对象描述",
        }
        state = status_labels.get(localization.status, "定位未完整完成")
        st.caption(f"Grounding DINO · {state} · {len(localization.candidates)} 个候选框")
        selection = localization.selection
        selection_labels = {
            "selected": "模型已关联任务主体，仍需结合现场确认",
            "ambiguous": "主体存在歧义",
            "abstained": "模型未确定主体",
            "unsupported": "当前目标无法可靠关联",
            "detection_only": "当前只有检测候选",
        }
        st.write(selection_labels.get(selection.status, "主体关联待确认"))
        if selection.reason:
            st.caption(selection.reason)
        if selection.selected_ids:
            st.caption("模型关联的候选 ID：" + "、".join(selection.selected_ids))
        if localization.candidates:
            try:
                st.image(
                    localization_overlay(result),
                    caption="候选对象位置；编号对应下方列表。框选结果需要现场确认。",
                    width="stretch",
                )
            except (ValueError, IndexError, OSError):
                st.warning("候选框预览暂时无法显示，可查看下方候选列表。")
            with st.expander("定位候选列表"):
                for index, candidate in enumerate(localization.candidates, start=1):
                    score = f" · 检测分数 {candidate.score:.3f}" if candidate.score is not None else ""
                    st.write(
                        f"{index}. {candidate.label_display or candidate.label_original} "
                        f"（ID：{candidate.object_id}）{score}"
                    )
                st.caption("检测分数表示模型关联强度，不代表正确率或主角确定程度。")
        else:
            st.info("本次没有可显示的候选框；构图建议应结合原图与现场判断。")

    if composition is None:
        return
    status_labels = {
        "grounded": "本次构图方案附有待核对支持范围的知识引用",
        "unverified": "本次没有可用的知识库依据，构图建议待验证",
        "unavailable": "本次无法生成构图方案",
        "demo": "演示构图结果，未调用真实模型",
    }
    label = status_labels.get(composition.status, "构图结果待验证")
    if composition.status == "grounded":
        st.info(label)
    else:
        st.warning(label)

    if composition.observations:
        with st.expander("画面观察与不确定项"):
            st.caption("以下为视觉模型候选观察，仍需核对原图；器材条件来自用户输入，不能当作原图拍摄事实。")
            for observation in composition.observations:
                st.write(f"- {observation}")
            for uncertainty in composition.uncertainties:
                st.caption(f"待确认：{uncertainty}")
    elif composition.uncertainties:
        for uncertainty in composition.uncertainties:
            st.caption(f"待确认：{uncertainty}")

    hits = getattr(result, "composition_knowledge_hits", [])
    hits_by_id = {hit.document_id: hit for hit in hits}
    action_labels = {
        "crop": "裁切",
        "camera_position": "调整机位",
        "focal_length": "调整焦段",
        "reshoot": "重新拍摄",
    }
    for index, proposal in enumerate(composition.proposals, start=1):
        action_label = action_labels.get(proposal.action_type, "调整构图")
        st.markdown(f"**方案 {index} · {action_label}：{proposal.goal}**")
        for action in proposal.actions:
            st.write(f"- {action}")
        if getattr(proposal, "action_evidence", []):
            with st.expander("模型动作原文（未核验）"):
                for action in proposal.action_evidence:
                    st.write(action)
        if getattr(proposal, "trial_actions", []) or getattr(proposal, "field_checks", []):
            st.caption("程序生成的现场比较说明；原文方向可追溯，改善效果仍需试取景。")
            for action in getattr(proposal, "trial_actions", []):
                target_label = {"camera": "相机", "subject": "主体", "light": "光源", "focus": "对焦"}.get(action.target, action.target)
                kind_label = {"lateral_translation": "横向移动", "depth_translation": "前后移动",
                              "height_translation": "升降机位", "pitch": "俯仰", "rotation": "旋转相机",
                              "subject_pose": "主体姿态", "light_position": "光源位置", "focus": "对焦"}.get(action.kind, action.kind)
                st.write(f"操作对象：{target_label}；动作：{kind_label}；方向：{action.direction}")
                if action.condition:
                    st.caption(f"动作条件：{action.condition}")
            for check in getattr(proposal, "field_checks", []):
                st.write(f"希望改善：{check.issue}")
                st.write(f"观察：{check.observe}")
                st.write(f"采用判据：{check.accept_when}")
                st.write(f"必须保护：{check.protect}")
        for reason in proposal.reasons:
            st.write(f"依据：{reason}")
        for tradeoff in proposal.tradeoffs:
            st.caption(f"取舍：{tradeoff}")
        for condition in proposal.conditions:
            st.caption(f"适用条件：{condition}")
        for limitation in proposal.limitations:
            st.caption(f"限制：{limitation}")
        if proposal.crop_bbox is not None:
            st.caption("建议裁切范围（左、上、右、下；归一化坐标）：" + str(proposal.crop_bbox))
        for knowledge_id in proposal.knowledge_ids:
            hit = hits_by_id.get(knowledge_id)
            if hit is not None:
                st.caption(f"候选引用存在：{hit.title} · {hit.document_id}；尚不能证明内容支持该动作。")
            else:
                st.caption(f"引用 {knowledge_id} 未匹配本次检索内容，需复核。")
        report = getattr(proposal, "knowledge_citation_review", None)
        if report is not None and (report.accepted or report.rejected):
            st.caption("该方案的知识原则引用；不能据此确认机位几何效果。")
            render_source_report(report)

    for note in composition.notes:
        st.caption(note)
    with st.expander("本次构图知识依据"):
        if not hits:
            st.write("未检索到已发布且适用的构图资料。上传到 GitHub 后仍需导入、审核并发布。")
        for hit in hits:
            st.write(f"{hit.title}（{hit.document_id}）")
            st.caption(f"来源：{hit.source} · 相关度 {hit.score:.3f}")
            st.write(hit.content[:600] + ("…" if len(hit.content) > 600 else ""))
            st.divider()


def render_result(result: PipelineResult) -> None:
    from camera_assistant.services.environment import environment_display_lines

    for line in environment_display_lines(result.scene):
        st.write(line)
    for uncertainty in result.scene.uncertainties:
        st.warning("待确认：" + uncertainty)
    recovery = getattr(result, "parameter_recovery", None)
    if recovery is not None:
        parameter_names = {"shooting_mode": "拍摄模式", "aperture": "光圈", "shutter_speed": "快门",
                           "iso": "ISO控制", "exposure_compensation": "曝光补偿", "focus_mode": "对焦",
                           "metering_mode": "测光", "drive_mode": "驱动模式", "white_balance": "白平衡"}
        missing_labels = "、".join(parameter_names.get(name, name) for name in recovery.missing_parameters)
        if recovery.status == "incomplete":
            st.warning("模型尚未给出完整参数方案。缺失项：" + missing_labels)
        elif recovery.status == "needs_confirmation":
            st.warning("参数方案包含需要用户核对的器材或现场条件。")
            if recovery.missing_parameters:
                st.warning("等待现场确认的参数：" + missing_labels)
        for confirmation in recovery.user_confirmations:
            st.warning(confirmation)
        if recovery.issues:
            with st.expander("参数阶段待处理项"):
                for issue in recovery.issues:
                    st.write(issue)
        if recovery.correction_attempted:
            st.caption(f"参数阶段已进行一次纠正；实际模型请求 {recovery.api_calls}/{recovery.call_limit} 次（含格式重试）。")
    render_composition(result)
    recommendation = result.recommendation
    camera_profile = getattr(result, "camera_profile", None)
    phone_result = isinstance(camera_profile, PhoneProfile)
    first_label = "镜头 / 景深" if phone_result else "光圈 APERTURE"
    shutter_label = "快门 SHUTTER"
    iso_label = "感光度 ISO"
    exposure_state = getattr(recommendation, "exposure_state", None)
    if exposure_state is not None and not phone_result:
        role_labels = {"manual_setting": "用户设置", "auto_target": "自动控制目标",
                       "observed": "观测值", "not_applicable": "不适用", "unknown": "需确认"}
        for key, label in (("aperture", first_label), ("shutter_speed", shutter_label),
                           ("iso", iso_label)):
            value = exposure_state.parameters.get(key)
            rendered = label + " · " + role_labels.get(value.role if value else "unknown", "需确认")
            if key == "aperture":
                first_label = rendered
            elif key == "shutter_speed":
                shutter_label = rendered
            else:
                iso_label = rendered
    result_title = (
        "手机操作建议 · 能力保守匹配"
        if phone_result
        else "建议设置 · 待测光和试拍验证"
    )
    scene_label = getattr(result.scene, "scene_label", "") or result.scene.scene_type
    candidate_scenes = getattr(result.scene, "candidate_scenes", [])
    recognition_evidence = getattr(result.scene, "recognition_evidence", [])
    st.markdown(
        f"""
        <div class="result-shell {"phone-result" if phone_result else ""}">
          <div class="result-title">{escaped(result_title)}</div>
          <div class="lcd">
            <div class="lcd-cell"><div class="lcd-label">{escaped(first_label)}</div><div class="lcd-value">{escaped(recommendation.aperture)}</div></div>
            <div class="lcd-cell"><div class="lcd-label">{escaped(shutter_label)}</div><div class="lcd-value">{escaped(recommendation.shutter_speed)}</div></div>
            <div class="lcd-cell"><div class="lcd-label">{escaped(iso_label)}</div><div class="lcd-value">{escaped(recommendation.iso)}</div></div>
          </div>
          <div class="secondary-readout">
            <div class="readout-row"><small>匹配机型</small><strong>{escaped(camera_profile.display_name if camera_profile else "通用机型")}</strong></div>
            <div class="readout-row"><small>拍摄模式</small><strong>{escaped(recommendation.shooting_mode)}</strong></div>
            <div class="readout-row"><small>曝光补偿</small><strong>{escaped(recommendation.exposure_compensation)}</strong></div>
            <div class="readout-row"><small>对焦</small><strong>{escaped(recommendation.focus_mode)}</strong></div>
            <div class="readout-row"><small>测光</small><strong>{escaped(recommendation.metering_mode)}</strong></div>
            <div class="readout-row"><small>连拍/驱动</small><strong>{escaped(recommendation.drive_mode)}</strong></div>
            <div class="readout-row"><small>白平衡</small><strong>{escaped(recommendation.white_balance)}</strong></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="scene-note">
          识别为 <strong>{escaped(scene_label)}</strong> · {escaped(result.scene.lighting)} ·
          主体运动 {escaped(result.scene.subject_motion)} · 视觉模型观察，需现场确认
        </div>
        """,
        unsafe_allow_html=True,
    )

    reason_col, risk_col = st.columns(2)
    with reason_col:
        st.subheader("为什么这样设置")
        for reason in recommendation.reasons:
            st.markdown(f"- {reason}")
    with risk_col:
        st.subheader("现场注意")
        for risk in recommendation.risks:
            st.markdown(f"- {risk}")

    st.subheader("拍完后怎么调")
    for adjustment in recommendation.adjustments:
        st.markdown(f"- {adjustment}")

    render_citation_review(result)

    if recommendation.validation_notes:
        with st.expander("参数校验记录"):
            st.caption("规则校验只核对已知能力与控制关系，不代表建议正确率或实拍效果。")
            for note in recommendation.validation_notes:
                st.write(f"✓ {note}")

    if recommendation.safety_notes:
        with st.expander("建议内容检查"):
            for note in recommendation.safety_notes:
                st.write(note)

    with st.expander("场景识别依据"):
        st.write(f"标准场景 ID：`{result.scene.scene_type}`")
        if candidate_scenes:
            st.write("候选场景：" + "、".join(candidate_scenes))
        for evidence in recognition_evidence:
            st.write(f"- {evidence}")
        for note in result.scene.notes:
            st.caption(note)

    if camera_profile:
        with st.expander("机型能力匹配"):
            if isinstance(camera_profile, PhoneProfile):
                st.write(f"**{camera_profile.display_name}** · {camera_profile.native_app}")
                st.caption(f"资料核对：{camera_profile.checked_at}；{camera_profile.region_scope}")
                for lens in camera_profile.lenses:
                    aperture = f"f/{lens.aperture:g}" if lens.aperture else "光圈未知"
                    st.write(f"{lens.name}：{aperture}（{lens.aperture_control}）")
                for note in camera_profile.notes:
                    st.write(f"- {note}")
                for index, url in enumerate(camera_profile.source_urls, start=1):
                    st.markdown(f"[官方资料 {index}]({url})")
            else:
                render_camera_details(camera_profile)

    render_knowledge_and_image(result)


def render_camera_details(camera_profile) -> None:
    st.write(
        f"**{camera_profile.display_name}** · {camera_profile.sensor_format} · "
        f"等效系数 {camera_profile.crop_factor:g}×"
    )
    st.write(
        f"标准 ISO {camera_profile.native_iso_min}–{camera_profile.native_iso_max}；"
        f"本系统保守自动 ISO 上限 {camera_profile.recommended_auto_iso_max}。"
    )
    st.write(
        f"机械快门最高 1/{camera_profile.max_mechanical_shutter}s；"
        f"机身防抖标称 {camera_profile.ibis_stops:g} 挡。"
    )
    for note in camera_profile.notes:
        st.write(f"- {note}")
    if camera_profile.source_url:
        st.markdown(f"[厂商资料]({camera_profile.source_url})")


def render_citation_review(result: PipelineResult) -> None:
    st.subheader("知识引用与支持范围")
    st.caption("未附有效引用的内容属于模型建议或程序规则；规则通过不代表实拍改善。通用原则不能证明具体参数、现场照度或反光效果。")
    report = getattr(result, "knowledge_citation_review", None)
    render_source_report(report)


def render_source_report(report) -> None:
    if report is None or not report.accepted:
        st.write("本次没有通过支持范围核对的知识引用。")
    if report is not None:
        for item in report.accepted:
            data = item.model_dump() if hasattr(item, "model_dump") else item
            citation = data.get("citation", {})
            st.write("知识原则：" + citation.get("claim", ""))
            st.caption(f"对应建议：{citation.get('claim_path', '')} · {citation.get('document_id', '')} · 版本 {citation.get('version', '')}")
            st.caption("支持范围：仅来源中的通用原则；具体设置仍需现场测光与试拍。")
            st.caption("适用条件：" + json.dumps(data.get("conditions", {}), ensure_ascii=False))
            for requirement in data.get("applicability_requires", []):
                st.caption("仍需现场确认：" + requirement)
            st.caption("来源：" + data.get("source", "") + " · " + data.get("source_license", ""))
            if data.get("source_url"):
                st.markdown(f"[知识来源]({data['source_url']})")
            st.caption("来源正文：" + citation.get("source_excerpt", ""))
            if data.get("usage_scope") == "isolated_test":
                st.warning("隔离测试资料，未经独立人审，未进入正式发布库。")
        if report.rejected:
            with st.expander("已隔离的候选引用"):
                st.caption("这些引用不能作为建议依据；独立参数和构图结果仍保留。")
                for item in report.rejected:
                    data = item.model_dump() if hasattr(item, "model_dump") else item
                    rejection_labels = {
                        "document_not_in_request": "本次未检索到此文档",
                        "version_not_in_request": "引用版本与本次资料不符",
                        "conditions_not_declared_or_invalid": "资料缺少有效适用条件记录",
                        "conditions_not_met": "适用条件未确认或不满足",
                        "source_excerpt_not_found": "引用原文未在本次来源正文中找到",
                        "final_claim_changed_or_unsupported_path": "引用所指的建议文本不一致或位置无效",
                        "claim_not_standalone_source_principle": "引用未对应来源中的完整独立原则",
                        "numeric_scene_or_geometry_not_supported": "通用原则不能支持具体参数、现场条件或几何效果",
                        "malformed_citation": "引用结构不完整",
                        "malformed_citation_list": "引用列表结构无效",
                        "citation_limit_exceeded": "引用数量超出检查范围",
                    }
                    st.write("引用未采用：" + rejection_labels.get(data.get("reason"), "引用未通过支持范围审核"))


def render_knowledge_and_image(result: PipelineResult) -> None:
    with st.expander("本次检索到的摄影知识"):
        for note in getattr(result, "knowledge_notes", []):
            st.caption(note)
        if not result.knowledge_hits:
            st.warning("知识库没有找到足够相关的内容。")
        for hit in result.knowledge_hits:
            st.markdown(f"**{hit.title}**　相关度 `{hit.score:.3f}`")
            st.caption(f"来源：{hit.source} · 文档：{hit.document_id}")
            if hit.metadata.get("usage_scope") == "isolated_test":
                st.caption("隔离软件测试资料 · 未独立人审 · 不属于正式发布库")
            elif hit.metadata.get("retrieval_backend") == "managed_keyword":
                st.caption(
                    f"已发布 · 库：{hit.metadata.get('library_id', '')} · "
                    f"版本：{hit.metadata.get('version', '')} · "
                    f"审核人：{hit.metadata.get('reviewer', '')}"
                )
            st.caption("适用范围：" + hit.metadata.get("conditions", "未声明；不能据此认定现场条件满足"))
            st.write(hit.content[:420] + ("…" if len(hit.content) > 420 else ""))
            st.divider()

    with st.expander("原图分析信息"):
        metrics = result.inspection.metrics
        st.json(
            {
                "分辨率": f"{metrics.width} × {metrics.height}",
                "平均亮度": metrics.mean_brightness,
                "对比度": metrics.contrast,
                "阴影比例": metrics.shadow_ratio,
                "高光比例": metrics.highlight_ratio,
                "清晰度分数": metrics.sharpness_score,
                "EXIF": result.inspection.exif.model_dump(exclude_none=True),
            }
        )


load_css()
migrate_session_state()
try:
    settings, pipeline = build_pipeline(PIPELINE_RESOURCE_VERSION)
except Exception:  # noqa: BLE001 - 页面边界统一脱敏，避免异常自动展示凭据。
    st.error(
        "应用配置尚未就绪。请检查本地 .env 中的模型、密钥与知识库配置，"
        "修改后重启。真实模式需要有效密钥；离线体验可设置 APP_DEMO_MODE=true。"
    )
    st.stop()
render_header(settings)
camera_profiles = pipeline.camera_knowledge.list_profiles()
camera_profile_names = {profile.profile_id: profile.display_name for profile in camera_profiles}

st.markdown('<div class="section-anchor" id="shoot"></div>', unsafe_allow_html=True)
with st.container(border=True):
    st.markdown(
        '<div class="panel-heading"><span>开始拍摄</span><strong>把现场交给小栗看看</strong></div>',
        unsafe_allow_html=True,
    )
    uploaded_file = st.file_uploader(
        "上传现场原图",
        type=["jpg", "jpeg", "png"],
        help="请上传手机或相机直接生成的图片，不要上传截图。当前版本最大支持 15 MB。",
        key="scene_photo",
        on_change=clear_photo_result,
    )
    if uploaded_file:
        st.image(uploaded_file, caption="现场图已上传", width="stretch")
        st.info("下一步：填写想拍出的效果，再点击「让小栗帮我配参数」开始分析。")

    device_name = st.radio(
        "拍摄设备",
        ["相机", "手机"],
        horizontal=True,
        key="capture_device",
        on_change=clear_device_result,
    )
    phone_profile_id = "generic_phone"
    phone_capture_mode = "auto"
    phone_lens_id = "main"
    phone_pro_confirm = False
    if device_name == "手机":
        model_query = st.text_input(
            "查找手机型号",
            placeholder="例如 iPhone 15、三星 S24 Ultra、小米14",
            key="phone_model_query",
            on_change=clear_device_result,
        )
        phone_matches = pipeline.phone_knowledge.search(model_query)
        if not phone_matches:
            st.info("该型号还未收录。会提供保守操作，不套用相近型号规格；可交给队员补充官方资料。")
            phone_matches = [pipeline.phone_knowledge.resolve("generic_phone")]
        phone_names = {profile.profile_id: profile.display_name for profile in phone_matches}
        phone_profile_id = st.selectbox(
            "手机型号",
            list(phone_names),
            format_func=phone_names.get,
            key="phone_model",
            on_change=clear_device_result,
        )
        selected_phone = pipeline.phone_knowledge.resolve(phone_profile_id)
        st.caption("请核对完整型号后缀；基础版、Pro、Ultra等不能互相替代。")
        phone_capture_mode = st.selectbox(
            "当前拍摄模式",
            selected_phone.modes,
            format_func=PHONE_MODE_NAMES.get,
            key="phone_mode",
            on_change=clear_device_result,
        )
        lens_names = {lens.lens_id: lens.name for lens in selected_phone.lenses}
        phone_lens_id = st.selectbox(
            "当前后置镜头",
            list(lens_names),
            format_func=lens_names.get,
            key="phone_lens",
            on_change=clear_device_result,
        )
        st.caption("本版只适配原生相机；第三方应用、前置相机、实时控制与HEIC暂未支持。")
        st.caption("手机资料核对不等于真机验证；模式/镜头不可用时请切回照片模式。")

    with st.form("recommendation_form"):
        intent = st.text_area(
            "你想拍出什么效果？",
            placeholder="例如：夜晚拍正在跑动的小狗，希望主体清晰、背景稍微虚化。",
            height=105,
            max_chars=500,
        )
        motion = st.radio(
            "主体会动吗？", ["静止", "缓慢", "快速", "不确定"], horizontal=True, index=3
        )
        capture_mode = st.radio("怎么拍？", ["手持", "三脚架"], horizontal=True)

        camera_profile_id = "generic_unknown"
        camera_format = "不清楚"
        focal_length = 0
        max_aperture = 0.0
        target_model_name = None
        target_lens_name = None
        camera_app = None
        os_major = 0
        shutter_type = None
        drive_mode = None
        focus_mode = None
        lighting_type = None
        if device_name == "手机" and phone_capture_mode == "pro":
            phone_pro_confirm = st.checkbox(
                "当前原生专业模式及所选镜头确实有 ISO、S/SPEED、WB、F 控件",
                key="phone_pro_confirm",
                help="只有已确认控制项才会提供方向性手动指导；本版不编造ISO/快门上下限。",
            )
        render_camera_inputs = device_name == "相机"
        with (
            st.expander("相机与镜头（选填）", expanded=False)
            if render_camera_inputs
            else st.container()
        ):
            if render_camera_inputs:
                camera_profile_id = st.selectbox(
                    "相机型号",
                    options=list(camera_profile_names),
                    format_func=lambda profile_id: camera_profile_names[profile_id],
                    help="选择具体机型后，系统会自动使用对应画幅、ISO、快门、防抖和对焦术语。",
                )
                camera_format = st.selectbox("相机画幅", ["不清楚", "全画幅", "APS-C", "M4/3"])
                focal_length = st.number_input(
                    "当前焦段（mm，可选）", min_value=0, max_value=1200, value=0
                )
                max_aperture = st.number_input(
                    "镜头最大光圈（可选）",
                    min_value=0.0,
                    max_value=32.0,
                    value=0.0,
                    step=0.1,
                )
                if camera_profile_id.startswith("generic_"):
                    target_model_name = st.text_input(
                        "其他相机的完整型号（可选）", max_chars=120,
                        help="用于匹配资料；未收录型号仍使用通用器材边界，不套用其他机型能力。",
                    ) or None
                target_lens_name = st.text_input(
                    "镜头完整型号（可选）", max_chars=160,
                    help="例如 RF50mm F1.8 STM；只填写你实际使用的镜头。",
                ) or None

        with st.expander("拍摄条件补充（选填）"):
            st.caption("只填写已确认的信息；不清楚的项目留空，相关专用资料会保守排除。")
            if device_name == "手机":
                if phone_profile_id.startswith("generic_"):
                    target_model_name = model_query.strip() or None
                camera_app = st.text_input(
                    "相机应用名称（可选）", max_chars=80,
                    help="已收录型号默认使用原生相机；第三方应用不套用原生控制能力。",
                ) or None
                os_major = st.number_input(
                    "系统大版本（0表示不清楚）", min_value=0, max_value=100, value=0,
                    help="例如 iOS 18 填18；不会从参考照片猜测系统版本。",
                )
            else:
                shutter_type = st.selectbox(
                    "当前快门类型", [None, "mechanical", "electronic", "efcs"],
                    format_func=lambda value: {
                        None: "不清楚", "mechanical": "机械快门", "electronic": "电子快门",
                        "efcs": "电子前帘",
                    }[value],
                )
                drive_mode = st.selectbox(
                    "当前驱动模式", [None, "single", "continuous"],
                    format_func=lambda value: {None: "不清楚", "single": "单张", "continuous": "连拍"}[value],
                )
                focus_mode = st.selectbox(
                    "当前对焦模式", [None, "AF-S", "AF-C", "MF"],
                    format_func=lambda value: {
                        None: "不清楚", "AF-S": "单次自动对焦", "AF-C": "连续自动对焦", "MF": "手动对焦",
                    }[value],
                )
            lighting_type = st.selectbox(
                "已确认的光线类型", [None, "natural", "continuous_artificial", "flickering_artificial", "mixed"],
                format_func=lambda value: {
                    None: "不清楚", "natural": "自然光", "continuous_artificial": "连续人造光",
                    "flickering_artificial": "已确认频闪的人造光", "mixed": "混合光",
                }[value],
                help="单张参考照片不能证明光源频闪；只有已确认时才选频闪。",
            )

        submitted = st.form_submit_button("让小栗帮我配参数", type="primary")

    analysis_feedback = st.container()

handheld = capture_mode == "手持"
tripod = capture_mode == "三脚架"

with analysis_feedback:
    if submitted:
        st.session_state.pop("last_result", None)
        if uploaded_file is None:
            st.error("先放入一张现场原图，小栗才能判断拍摄环境。")
        elif len(intent.strip()) < 2:
            st.error("请用一句话告诉小栗你想拍出的效果。")
        else:
            try:
                user_request = UserRequest(
                    intent=intent.strip(),
                    subject_motion=motion,
                    handheld=handheld,
                    tripod=tripod,
                    camera_format=camera_format,
                    camera_profile_id=camera_profile_id,
                    focal_length_mm=focal_length or None,
                    max_aperture=max_aperture or None,
                    device_type="phone" if device_name == "手机" else "camera",
                    phone_profile_id=phone_profile_id,
                    phone_capture_mode=phone_capture_mode,
                    phone_lens_id=phone_lens_id,
                    phone_pro_controls_confirmed=phone_pro_confirm,
                    target_model_name=target_model_name,
                    target_lens_name=target_lens_name,
                    camera_app=camera_app,
                    os_major=int(os_major) if os_major else None,
                    shutter_type=shutter_type,
                    drive_mode=drive_mode,
                    focus_mode=focus_mode,
                    lighting_type=lighting_type,
                )
                result = analyze_with_progress(uploaded_file.getvalue(), user_request)
                st.session_state["last_result"] = result
            except ImageValidationError as exc:
                st.error(str(exc))
            except ValidationError:
                st.error("输入或模型返回的数据格式不符合要求。请检查焦段、光圈后重试。")
            except ModelServiceError as exc:
                st.error(str(exc))
            except httpx.TimeoutException:
                st.error("模型请求超时，请检查网络并稍后重试。")
            except httpx.HTTPError:
                st.error("模型服务暂时无法连接，请检查网络、服务地址与密钥配置。")
            except (ValueError, KeyError, TypeError, RuntimeError, OSError):
                st.error("这次分析没有完成，请检查模型与知识库配置后重试。")
            except Exception:  # noqa: BLE001 - 未预见的服务错误也不能回显敏感请求。
                st.error("这次分析未能完成，请稍后重试或联系项目维护者检查本机运行记录。")

st.markdown('<div class="section-anchor" id="result"></div>', unsafe_allow_html=True)
with st.container(border=True):
    st.markdown(
        '<div class="panel-heading result-heading"><span>拍摄方案</span><strong>照着设备界面操作</strong></div>',
        unsafe_allow_html=True,
    )
    if "last_result" in st.session_state:
        render_result(st.session_state["last_result"])
    elif not submitted:
        empty_title = "等待开始分析" if uploaded_file else "等待一张现场图"
        empty_hint = (
            "填写完成后，小栗会给出模式、镜头与曝光操作指导"
            if device_name == "手机"
            else "填写完成后，小栗会把光圈、快门和 ISO 放在这里"
        )
        st.markdown(
            f"""
            <div class="empty-viewfinder">
              <div class="viewfinder-reticle" aria-hidden="true"></div>
              <div class="empty-copy"><b>{empty_title}</b><span>{empty_hint}</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.markdown(
    """
    <nav class="mobile-nav" aria-label="页面导航">
      <a href="#home"><span>⌂</span>首页</a>
      <a href="#shoot" class="active"><span>◎</span>拍摄</a>
      <a href="#result"><span>▣</span>方案</a>
    </nav>
    """,
    unsafe_allow_html=True,
)
