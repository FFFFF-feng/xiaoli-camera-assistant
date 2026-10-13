from __future__ import annotations

import base64
import html
import io
from pathlib import Path

import httpx
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent

from camera_assistant.config import Settings
from camera_assistant.models import PipelineResult, UserRequest
from camera_assistant.pipeline import CameraAssistantPipeline
from camera_assistant.services.cloud import ModelServiceError
from camera_assistant.services.image_analyzer import ImageValidationError

st.set_page_config(
    page_title="小栗取景参谋｜相机参数助手",
    page_icon="📷",
    layout="centered",
    initial_sidebar_state="collapsed",
)

SESSION_SCHEMA_VERSION = 6
PIPELINE_RESOURCE_VERSION = 4


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
            <p>看懂现场，也看懂你的相机。</p>
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
        "grounded": "本次构图方案附有知识库引用",
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
                st.caption(f"引用：{hit.title} · {hit.document_id} · 来源：{hit.source}")
            else:
                st.caption(f"引用 {knowledge_id} 未匹配本次检索内容，需复核。")

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
    render_composition(result)
    recommendation = result.recommendation
    camera_profile = getattr(result, "camera_profile", None)
    scene_label = getattr(result.scene, "scene_label", "") or result.scene.scene_type
    candidate_scenes = getattr(result.scene, "candidate_scenes", [])
    recognition_evidence = getattr(result.scene, "recognition_evidence", [])
    st.markdown(
        f"""
        <div class="result-shell">
          <div class="result-title">建议设置 · 置信度 {recommendation.confidence:.0%}</div>
          <div class="lcd">
            <div class="lcd-cell"><div class="lcd-label">光圈 APERTURE</div><div class="lcd-value">{escaped(recommendation.aperture)}</div></div>
            <div class="lcd-cell"><div class="lcd-label">快门 SHUTTER</div><div class="lcd-value">{escaped(recommendation.shutter_speed)}</div></div>
            <div class="lcd-cell"><div class="lcd-label">感光度 ISO</div><div class="lcd-value">{escaped(recommendation.iso)}</div></div>
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
          主体运动 {escaped(result.scene.subject_motion)} · 场景置信度 {result.scene.confidence:.0%}
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

    if recommendation.validation_notes:
        with st.expander("参数校验记录"):
            for note in recommendation.validation_notes:
                st.write(f"✓ {note}")

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

    with st.expander("本次检索到的摄影知识"):
        for note in getattr(result, "knowledge_notes", []):
            st.caption(note)
        if not result.knowledge_hits:
            st.warning("知识库没有找到足够相关的内容。")
        for hit in result.knowledge_hits:
            st.markdown(f"**{hit.title}**　相关度 `{hit.score:.3f}`")
            st.caption(f"来源：{hit.source} · 文档：{hit.document_id}")
            if hit.metadata.get("retrieval_backend") == "managed_keyword":
                st.caption(
                    f"已发布 · 库：{hit.metadata.get('library_id', '')} · "
                    f"版本：{hit.metadata.get('version', '')} · "
                    f"审核人：{hit.metadata.get('reviewer', '')}"
                )
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
    )
    if uploaded_file:
        st.image(uploaded_file, caption="小栗正在观察这张现场图", width="stretch")

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

        with st.expander("相机与镜头（选填）"):
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

        submitted = st.form_submit_button("让小栗帮我配参数", type="primary")

handheld = capture_mode == "手持"
tripod = capture_mode == "三脚架"

st.markdown('<div class="section-anchor" id="result"></div>', unsafe_allow_html=True)
with st.container(border=True):
    st.markdown(
        '<div class="panel-heading result-heading"><span>拍摄方案</span><strong>照着相机屏幕设置</strong></div>',
        unsafe_allow_html=True,
    )
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
                )
                with st.spinner("小栗正在识别场景、定位候选并查阅拍摄知识…"):
                    result = pipeline.run(uploaded_file.getvalue(), user_request)
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

    if "last_result" in st.session_state:
        render_result(st.session_state["last_result"])
    elif not submitted:
        st.markdown(
            """
            <div class="empty-viewfinder">
              <div class="viewfinder-reticle" aria-hidden="true"></div>
              <div class="empty-copy"><b>等待一张现场图</b><span>填写完成后，小栗会把光圈、快门和 ISO 放在这里</span></div>
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
