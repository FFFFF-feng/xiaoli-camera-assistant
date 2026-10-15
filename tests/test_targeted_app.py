import base64
import json
from pathlib import Path

import test_app as fixtures
from streamlit.testing.v1 import AppTest

from camera_assistant.models import PipelineResult
from camera_assistant.pipeline import CameraAssistantPipeline

offline_app = fixtures.offline_app
uploaded_photo = fixtures.uploaded_photo
submit_button = fixtures.submit_button

ROOT = Path(__file__).resolve().parents[1]


def saved(case):
    data = json.loads(
        (ROOT / f"data/history/main-acceptance-20261014/live/{case}-pipeline.json").read_text(
            encoding="utf-8"))
    data["inspection"]["model_image_data_url"] = "data:image/jpeg;base64," + base64.b64encode(
        (ROOT / f"data/history/main-acceptance-20261014/live/{case}-sent.jpg").read_bytes()).decode("ascii")
    return PipelineResult.model_validate(data)


def test_missing_parameters_have_readable_labels_and_existing_composition(monkeypatch, uploaded_photo):
    result = saved("D17")
    monkeypatch.setattr(CameraAssistantPipeline, "run", lambda *args, **kwargs: result)
    app = AppTest.from_file(ROOT / "app.py", default_timeout=15).run()
    app.text_area[0].set_value("保留通道与棚架")
    submit_button(app).click().run()
    assert not app.exception
    assert any("缺失项：快门" in item.value for item in app.warning)
    assert any("方案 1" in item.value for item in app.markdown)
    assert any("知识引用与支持范围" in item.value for item in app.subheader)
    assert any("模型建议或程序规则" in item.value for item in app.caption)


def test_composition_model_words_and_program_checks_are_distinct(monkeypatch, uploaded_photo):
    from camera_assistant.composition_models import CompositionAdvice
    from camera_assistant.services.advice_review import final_composition_review
    result = saved("D01")
    raw = json.loads((ROOT / "data/history/main-acceptance-20261014/live/D01-composition-structured-1.json").read_text(encoding="utf-8"))
    from camera_assistant.models import UserRequest
    manifest = json.loads((ROOT / "data/history/main-acceptance-20261014/live/manifest.json").read_text(encoding="utf-8"))
    request = UserRequest.model_validate(next(case["request"] for case in manifest["cases"] if case["id"] == "D01"))
    result.composition = final_composition_review(CompositionAdvice.model_validate(raw),
        result.recommendation, request, result.scene, result.camera_profile)
    monkeypatch.setattr(CameraAssistantPipeline, "run", lambda *args, **kwargs: result)
    app = AppTest.from_file(ROOT / "app.py", default_timeout=15).run()
    app.text_area[0].set_value("保留笑脸和眼睛，比较眼镜反光")
    submit_button(app).click().run()
    assert not app.exception
    assert any("模型动作原文" in item.label for item in app.expander)
    assert any("程序生成的现场比较" in item.value for item in app.caption)
    text = " ".join(item.value for item in app.markdown)
    assert "观察：" in text and "采用判据：" in text


def test_valid_source_display_is_explicitly_an_isolated_software_fixture(monkeypatch, uploaded_photo):
    from test_knowledge_citations import PRINCIPLE, candidate, hit

    from camera_assistant.services.knowledge_citations import (
        citation_candidates,
        review_knowledge_citations,
    )

    result = saved("D01")
    knowledge = hit(usage_scope="isolated_test", conditions='{"motion":"slow"}',
                    requires='["现场测光或试拍"]')
    result.knowledge_hits = [knowledge]
    result.recommendation = result.recommendation.model_copy(update={
        "reasons": [PRINCIPLE], "knowledge_citations": citation_candidates([candidate()]),
    })
    result.knowledge_citation_review = review_knowledge_citations(
        result.recommendation, [knowledge], {"motion": "slow"})
    monkeypatch.setattr(CameraAssistantPipeline, "run", lambda *args, **kwargs: result)
    app = AppTest.from_file(ROOT / "app.py", default_timeout=15).run()
    app.text_area[0].set_value("来源展示软件测试，非真实生成")
    submit_button(app).click().run()
    assert not app.exception
    assert any("知识原则：" in item.value and PRINCIPLE in item.value for item in app.markdown)
    assert any("知识来源" in item.value and "wikibooks.org" in item.value for item in app.markdown)
    assert any("仍需现场确认：现场测光或试拍" in item.value for item in app.caption)
    assert any("隔离测试资料，未经独立人审" in item.value for item in app.warning)
