from __future__ import annotations

import base64
import html
from pathlib import Path

import httpx
import streamlit as st

ROOT = Path(__file__).resolve().parent

from camera_assistant.config import Settings
from camera_assistant.models import PipelineResult, UserRequest
from camera_assistant.pipeline import CameraAssistantPipeline
from camera_assistant.services.image_analyzer import ImageValidationError

st.set_page_config(
    page_title="小栗取景参谋｜相机参数助手",
    page_icon="📷",
    layout="centered",
    initial_sidebar_state="collapsed",
)

SESSION_SCHEMA_VERSION = 4
PIPELINE_RESOURCE_VERSION = 2


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


def render_result(result: PipelineResult) -> None:
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
        if not result.knowledge_hits:
            st.warning("知识库没有找到足够相关的内容。")
        for hit in result.knowledge_hits:
            st.markdown(f"**{hit.title}**　相关度 `{hit.score:.3f}`")
            st.caption(f"来源：{hit.source} · 文档：{hit.document_id}")
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
settings, pipeline = build_pipeline(PIPELINE_RESOURCE_VERSION)
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
        if uploaded_file is None:
            st.error("先放入一张现场原图，小栗才能判断拍摄环境。")
        elif len(intent.strip()) < 2:
            st.error("请用一句话告诉小栗你想拍出的效果。")
        else:
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
            try:
                with st.spinner("小栗正在识别场景、翻知识手册并检查机型…"):
                    result = pipeline.run(uploaded_file.getvalue(), user_request)
                st.session_state["last_result"] = result
            except ImageValidationError as exc:
                st.error(str(exc))
            except (ValueError, KeyError, TypeError, httpx.HTTPError) as exc:
                st.error(f"这次分析没有完成：{exc}")

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
