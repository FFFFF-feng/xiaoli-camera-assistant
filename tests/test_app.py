from io import BytesIO
from pathlib import Path

import httpx
import pytest
import streamlit as st
from PIL import Image
from streamlit.testing.v1 import AppTest

from camera_assistant.pipeline import CameraAssistantPipeline

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_app(monkeypatch):
    """Never inherit the user's real provider configuration or cached pipeline."""
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    monkeypatch.setenv("CAMERA_AI_PRESET", "custom")
    monkeypatch.setenv("CAMERA_AI_API_KEY", "")
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_MODE", "legacy")
    monkeypatch.setenv("CAMERA_AI_COMPOSITION_ENABLED", "false")
    monkeypatch.setenv("CAMERA_AI_DETECTOR_ENABLED", "false")

    def forbidden_http(*args, **kwargs):
        pytest.fail("Main page regression tests must not call a live model.")

    monkeypatch.setattr(httpx.Client, "post", forbidden_http)
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


@pytest.fixture
def uploaded_photo(monkeypatch):
    image = BytesIO()
    Image.new("RGB", (100, 80), (90, 110, 120)).save(image, format="JPEG")
    content = image.getvalue()
    # AppTest has no upload API; exercise the actual preview and submission path.
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: BytesIO(content))
    return content


def submit_button(app):
    return next(button for button in app.button if button.label == "让小栗帮我配参数")


def test_app_starts_in_demo_mode() -> None:
    app = AppTest.from_file(ROOT / "app.py", default_timeout=10).run()

    assert not app.exception
    assert app.file_uploader[0].label == "上传现场原图"
    assert app.text_area[0].label == "你想拍出什么效果？"
    assert app.selectbox[0].label == "相机型号"
    assert any(button.label == "让小栗帮我配参数" for button in app.button)


def test_upload_only_shows_ready_state_without_starting_analysis(monkeypatch, uploaded_photo):
    calls = []
    monkeypatch.setattr(CameraAssistantPipeline, "run", lambda *args, **kwargs: calls.append(args))
    app = AppTest.from_file(ROOT / "app.py", default_timeout=10).run()

    assert not app.exception
    assert not calls
    assert not app.status
    assert "last_result" not in app.session_state
    assert app.get("image")[0].captions == ["现场图已上传"]
    assert any("点击「让小栗帮我配参数」开始分析" in item.value for item in app.info)
    assert any("等待开始分析" in item.value for item in app.markdown)


@pytest.mark.parametrize("intent", ["", "   ", "拍"])
def test_submit_requires_a_goal_before_starting_analysis(monkeypatch, uploaded_photo, intent):
    calls = []
    monkeypatch.setattr(CameraAssistantPipeline, "run", lambda *args, **kwargs: calls.append(args))
    app = AppTest.from_file(ROOT / "app.py", default_timeout=10).run()
    app.text_area[0].set_value(intent)
    submit_button(app).click().run()

    assert not app.exception
    assert not calls
    assert not app.status
    assert [error.value for error in app.error] == ["请用一句话告诉小栗你想拍出的效果。"]
    assert "last_result" not in app.session_state


def test_submitted_analysis_reports_progress_and_renders_result(monkeypatch, uploaded_photo):
    calls = []
    original_run = CameraAssistantPipeline.run

    def observed_run(self, content, request, *, on_progress=None):
        calls.append((content, request, on_progress))
        return original_run(self, content, request, on_progress=on_progress)

    monkeypatch.setattr(CameraAssistantPipeline, "run", observed_run)
    app = AppTest.from_file(ROOT / "app.py", default_timeout=10).run()
    app.text_area[0].set_value("拍摄清晰的风景")
    submit_button(app).click().run()

    assert not app.exception
    assert not app.error
    assert len(calls) == 1
    assert calls[0][0] == uploaded_photo
    assert calls[0][1].intent == "拍摄清晰的风景"
    assert callable(calls[0][2])
    assert app.status[0].state == "complete"
    assert "分析完成" in app.status[0].label
    assert any("正在识别画面" in item.value for item in app.status[0].markdown)
    assert any("正在校验拍摄建议" in item.value for item in app.status[0].markdown)
    result = app.session_state["last_result"]
    assert result.recommendation.shutter_speed != "未生成"
    assert any(result.recommendation.shutter_speed in item.value for item in app.markdown)


def test_failed_analysis_marks_status_and_sanitizes_service_details(monkeypatch, uploaded_photo):
    def failing_run(self, content, request, *, on_progress=None):
        on_progress("正在识别画面中的主体和光线…")
        raise RuntimeError("synthetic-private-provider-detail")

    monkeypatch.setattr(CameraAssistantPipeline, "run", failing_run)
    app = AppTest.from_file(ROOT / "app.py", default_timeout=10).run()
    app.text_area[0].set_value("拍摄清晰的风景")
    submit_button(app).click().run()

    assert not app.exception
    assert app.status[0].state == "error"
    assert "未完成" in app.status[0].label
    assert [error.value for error in app.error] == [
        "这次分析没有完成，请检查模型与知识库配置后重试。"
    ]
    assert "last_result" not in app.session_state
    assert "synthetic-private-provider-detail" not in " ".join(
        [item.value for item in app.markdown] + [item.value for item in app.error]
    )


def test_p03_window_environment_uncertainty_is_visible_in_final_result(
    monkeypatch, uploaded_photo
):
    import json

    from camera_assistant.models import SceneAnalysis
    from camera_assistant.services.vision import DemoVisionAnalyzer

    saved = json.loads(
        (ROOT / "data/history/main-fix-final-20261014/P03-pipeline.json").read_text(
            encoding="utf-8"
        )
    )
    window_scene = SceneAnalysis.model_validate(saved["scene"])
    monkeypatch.setattr(DemoVisionAnalyzer, "analyze", lambda *args, **kwargs: window_scene)
    app = AppTest.from_file(ROOT / "app.py", default_timeout=10).run()
    app.text_area[0].set_value("保留完整窗框，远处树林的层次要更清楚")
    submit_button(app).click().run()

    assert not app.exception
    assert not app.error
    result = app.session_state["last_result"]
    assert result.scene.environment == "outdoor"
    assert result.scene.environment_context.shooting_location == "unknown"
    assert result.scene.environment_context.content_environment == "mixed"
    assert any("拍摄位置未确认" in item.value for item in app.warning)
    assert any("照度" in item.value for item in app.warning)
    assert any("窗框和室外风景" in item.value for item in app.markdown)
