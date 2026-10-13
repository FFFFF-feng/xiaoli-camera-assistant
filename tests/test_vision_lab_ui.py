import os
from pathlib import Path

import pytest
from streamlit.proto.TextInput_pb2 import TextInput as TextInputProto
from streamlit.testing.v1 import AppTest
from test_vision_lab_core import image_bytes

ROOT = Path(__file__).resolve().parents[1]


def by_label(elements, label):
    return next(element for element in elements if element.label == label)


def test_lab_starts_without_key():
    app = AppTest.from_file(ROOT / "vision_lab.py", default_timeout=20).run()
    assert not app.exception
    assert app.file_uploader[0].label == "上传测试照片"
    assert by_label(app.button, "运行测试").disabled


def test_run_rerun_review_history_no_duplicate_calls(monkeypatch, tmp_path):
    from vision_lab_tool import runner

    calls = []
    original = runner.invoke

    def counted(*args, **kwargs):
        calls.append(args[0].name)
        return original(*args, **kwargs)

    monkeypatch.setattr(runner, "invoke", counted)
    monkeypatch.setenv("VISION_LAB_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(ROOT / "vision_lab.py", default_timeout=20)
    app.session_state["lab_profile"] = "模拟 / 其他模型"
    app.session_state["lab_image_bytes"] = image_bytes()
    app.run()
    by_label(app.button, "运行测试").click().run()
    assert not app.exception and len(calls) == 2
    run = app.session_state["lab_active_run"]
    assert sum(item.value == "**场景**" for item in app.markdown) == 2
    assert sum(item.value == "**主体**" for item in app.markdown) == 2
    raw_panels = [item for item in app.expander if item.label == "原始回答与 JSON（排查用）"]
    assert len(raw_panels) == 2 and all(not item.proto.expanded for item in raw_panels)
    original_answers = [(result.raw_answer, result.parsed) for result in run.results]
    run_id = run.run_id
    by_label(app.toggle, "隐藏模型名称（盲评）").set_value(True).run()
    assert not app.exception and len(calls) == 2
    assert app.session_state["lab_active_run"].run_id == run_id
    by_label(app.checkbox, "已完成人工评测 · 模型 A").set_value(True).run()
    assert app.session_state["lab_active_run"].evaluations[run.results[0].result_id].reviewed
    assert [
        (r.raw_answer, r.parsed) for r in app.session_state["lab_active_run"].results
    ] == original_answers
    by_label(app.button, "保存记录与评测").click().run()
    assert not app.exception and len(calls) == 2
    by_label(app.button, "重新打开所选历史").click().run()
    assert not app.exception and len(calls) == 2
    assert app.session_state["lab_active_run"].evaluations[run.results[0].result_id].reviewed
    app.run()
    assert not app.exception and len(calls) == 2


def test_switch_image_hides_old_result_and_annotations(monkeypatch, tmp_path):
    monkeypatch.setenv("VISION_LAB_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(ROOT / "vision_lab.py", default_timeout=20)
    app.session_state["lab_profile"] = "模拟 / 其他模型"
    app.session_state["lab_image_bytes"] = image_bytes()
    app.run()
    by_label(app.button, "运行测试").click().run()
    run_id = app.session_state["lab_active_run"].run_id
    app.session_state["lab_image_bytes"] = image_bytes(size=(90, 60))
    app.run()
    assert not app.exception and app.session_state["lab_active_run"] is None
    assert run_id in app.session_state["lab_memory_runs"]


def test_model_descriptions_are_literal_text_not_markdown(monkeypatch, tmp_path):
    monkeypatch.setenv("VISION_LAB_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(ROOT / "vision_lab.py", default_timeout=20)
    app.session_state["lab_profile"] = "模拟 / 其他模型"
    app.session_state["lab_image_bytes"] = image_bytes()
    app.run()
    by_label(app.button, "运行测试").click().run()
    run = app.session_state["lab_active_run"]
    sentinel = "![模型原文](https://example.invalid/track) **不要解释为格式**"
    run.results[0].parsed["composition_clues"] = [sentinel]
    app.run()
    assert not app.exception
    assert sentinel in [item.value for item in app.text]
    assert all(sentinel not in item.value for item in app.markdown)
    assert run.results[0].parsed["composition_clues"] == [sentinel]


def test_history_without_photo_reupload_preserves_unsaved_review(monkeypatch, tmp_path):
    from test_vision_lab_records import run

    from vision_lab_tool.storage import Store

    monkeypatch.setenv("VISION_LAB_DATA_DIR", str(tmp_path))
    saved = run()
    Store(tmp_path).save_run(saved)
    app = AppTest.from_file(ROOT / "vision_lab.py", default_timeout=20).run()
    by_label(app.button, "重新打开所选历史").click().run()
    by_label(app.text_area, "人工参考备注 / 未知条件").set_value("未保存续评").run()
    app.session_state["lab_image_bytes"] = image_bytes()
    app.run()
    assert not app.exception
    assert app.session_state["lab_active_run"].run_id == saved.run_id
    assert app.session_state["lab_active_run"].reference.notes == "未保存续评"


def test_advice_mode_has_shared_context_and_valid_proposals(monkeypatch, tmp_path):
    monkeypatch.setenv("VISION_LAB_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(ROOT / "vision_lab.py", default_timeout=20)
    app.session_state["lab_profile"] = "模拟 / 其他模型"
    app.session_state["lab_image_bytes"] = image_bytes()
    app.run()
    by_label(app.radio, "实验模式").set_value("建议测试").run()
    by_label(app.text_area, "共同用户目标").set_value("突出主体").run()
    by_label(app.text_area, "共同器材事实 / 未知条件").set_value("焦距未知").run()
    by_label(app.button, "运行测试").click().run()
    assert not app.exception
    record = app.session_state["lab_active_run"]
    assert record.mode == "advice" and record.context["include_exif"] is False
    assert "突出主体" in record.prompt and "焦距未知" in record.prompt
    assert all(result.status == "ok" for result in record.results)
    assert all(len(result.parsed["proposals"]) == 2 for result in record.results)
    assert sum(item.value == "##### 方案 1 · 裁切现有照片" for item in app.markdown) == 2
    assert sum(item.value == "##### 方案 2 · 重新拍摄" for item in app.markdown) == 2


def test_simple_screen_defaults_to_four_requested_models(monkeypatch, tmp_path):
    monkeypatch.setenv("VISION_LAB_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(ROOT / "vision_lab.py", default_timeout=20).run()
    assert not app.exception
    selected = by_label(app.multiselect, "选择要比较的模型（2～4 个）").value
    names = {c.config_id: c.name for c in app.session_state["lab_configs"]}
    assert [names[cid] for cid in selected] == [
        "Qwen3-VL Plus",
        "Doubao-Seed 2.1 Lite",
        "Doubao-Seed 2.1 Pro",
        "GLM-4.6V",
    ]
    assert by_label(app.text_input, "百炼 API Key（Qwen）").proto.type == TextInputProto.PASSWORD
    assert (
        by_label(app.text_input, "火山方舟 API Key（两个 Doubao 共用）").proto.type
        == TextInputProto.PASSWORD
    )
    assert by_label(app.text_input, "智谱 API Key（GLM）").proto.type == TextInputProto.PASSWORD
    assert any("最长边" in item.value and "4000" in item.value for item in app.caption)


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI feature")
def test_key_save_reopen_and_delete_make_no_network_calls(monkeypatch, tmp_path):
    import httpx

    from vision_lab_tool.credentials import KeyVault

    monkeypatch.setenv("VISION_LAB_DATA_DIR", str(tmp_path))
    calls = []

    def unexpected_request(*args, **kwargs):
        calls.append(1)
        raise AssertionError("密钥配置不允许触发模型请求")

    monkeypatch.setattr(httpx.Client, "post", unexpected_request)
    app = AppTest.from_file(ROOT / "vision_lab.py", default_timeout=20).run()
    by_label(app.text_input, "百炼 API Key（Qwen）").set_value("qa-qwen-key")
    by_label(app.text_input, "火山方舟 API Key（两个 Doubao 共用）").set_value("qa-ark-key")
    by_label(app.text_input, "智谱 API Key（GLM）").set_value("qa-glm-key")
    by_label(app.button, "保存 API Key 到本机").click().run()
    assert not app.exception and calls == []
    vault = KeyVault(tmp_path / "credentials.dpapi.json")
    assert vault.load()["ARK_API_KEY"] == "qa-ark-key"
    assert "qa-ark-key" not in (tmp_path / "credentials.dpapi.json").read_text("utf-8")
    assert by_label(app.text_input, "火山方舟 API Key（两个 Doubao 共用）").value == ""
    reopened = AppTest.from_file(ROOT / "vision_lab.py", default_timeout=20).run()
    assert not reopened.exception
    assert reopened.session_state["lab_saved_keys"]["ZHIPU_API_KEY"] == "qa-glm-key"
    by_label(reopened.selectbox, "删除哪一份本机密钥").set_value("ARK_API_KEY").run()
    by_label(reopened.button, "删除选中的本机密钥").click().run()
    assert not reopened.exception and calls == []
    assert vault.load() == {"DASHSCOPE_API_KEY": "qa-qwen-key", "ZHIPU_API_KEY": "qa-glm-key"}


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI feature")
def test_saved_key_echo_in_annotations_is_scrubbed_from_exports(monkeypatch, tmp_path):
    from vision_lab_tool.credentials import KeyVault

    monkeypatch.setenv("VISION_LAB_DATA_DIR", str(tmp_path))
    KeyVault(tmp_path / "credentials.dpapi.json").update({"ARK_API_KEY": "qa-private-key"})
    app = AppTest.from_file(ROOT / "vision_lab.py", default_timeout=20)
    app.session_state["lab_profile"] = "模拟 / 其他模型"
    app.session_state["lab_image_bytes"] = image_bytes()
    app.run()
    by_label(app.button, "运行测试").click().run()
    by_label(app.text_area, "人工参考备注 / 未知条件").set_value("qa-private-key").run()
    by_label(app.button, "保存记录与评测").click().run()
    assert not app.exception
    assert all(
        "qa-private-key" not in path.read_text("utf-8")
        for path in (tmp_path / "runs").glob("*.json")
    )


def test_invalid_saved_configs_are_not_overwritten_by_preset_migration(monkeypatch, tmp_path):
    monkeypatch.setenv("VISION_LAB_DATA_DIR", str(tmp_path))
    path = tmp_path / "configs.json"
    original = b'{"future-schema": "recoverable custom settings"}'
    path.write_bytes(original)
    app = AppTest.from_file(ROOT / "vision_lab.py", default_timeout=20).run()
    assert not app.exception
    assert path.read_bytes() == original


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI feature")
def test_blind_mode_retains_session_key_priority(monkeypatch, tmp_path):
    from vision_lab_tool import runner
    from vision_lab_tool.credentials import KeyVault
    from vision_lab_tool.models import ModelConfig

    monkeypatch.setenv("VISION_LAB_DATA_DIR", str(tmp_path))
    KeyVault(tmp_path / "credentials.dpapi.json").update({"ARK_API_KEY": "saved-test-token"})
    custom = ModelConfig(
        config_id="fake-chat",
        name="Fake Chat",
        provider="测试",
        protocol="chat",
        base_url="https://test.invalid/v1",
        model_id="fake",
        key_env="ARK_API_KEY",
    )
    selected_keys = []
    original_invoke = runner.invoke

    def mocked(config, prompt, image, mode, key, transport=None):
        if config.config_id == custom.config_id:
            selected_keys.append(key)
        # Never use a network transport, even for a configuration labeled chat.
        return original_invoke(
            config.model_copy(update={"protocol": "mock"}), prompt, image, mode, ""
        )

    monkeypatch.setattr(runner, "invoke", mocked)
    app = AppTest.from_file(ROOT / "vision_lab.py", default_timeout=20)
    app.session_state["lab_profile"] = "模拟 / 其他模型"
    app.session_state["lab_image_bytes"] = image_bytes()
    app.session_state["lab_configs"] = [
        custom,
        ModelConfig(config_id="mock", name="Mock", provider="模拟", protocol="mock"),
    ]
    app.session_state["lab_profile_selections"] = {"模拟 / 其他模型": ["fake-chat", "mock"]}
    app.run()
    by_label(app.text_input, "临时密钥 · Fake Chat").set_value("temporary-test-token").run()
    by_label(app.button, "运行测试").click().run()
    by_label(app.toggle, "隐藏模型名称（盲评）").set_value(True).run()
    app.run()  # a second rerun exercises cleanup of the hidden password widget
    by_label(app.button, "运行测试").click().run()
    assert not app.exception
    assert selected_keys == ["temporary-test-token", "temporary-test-token"]
