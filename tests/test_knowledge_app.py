"""独立知识库工作台的隔离交互测试，不触碰项目中的真实数据库。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.knowledge.ui_helpers import template_json
from camera_assistant.knowledge.uploads import MAX_UPLOAD_BYTES

APP_PATH = Path(__file__).resolve().parents[1] / "knowledge_app.py"


@pytest.fixture
def workbench(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[AppTest, KnowledgeStore]:
    database = tmp_path / "isolated-knowledge.db"
    monkeypatch.setenv("KNOWLEDGE_DB_PATH", str(database))
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    monkeypatch.setenv("CAMERA_AI_API_KEY", "")
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_MODE", "legacy")
    app = AppTest.from_file(APP_PATH, default_timeout=15).run()
    assert not app.exception
    return app, KnowledgeStore(database)


def record_json(knowledge_id: str = "ui-composition-001", library_id: str = "composition") -> str:
    record = json.loads(template_json(library_id))
    record.update(
        knowledge_id=knowledge_id,
        title="界面回归测试记录",
        author="测试整理者",
        content="仅用于隔离测试，不是正式摄影知识。",
    )
    # 整理者未显式授权时，模型必须保持检索许可默认关闭。
    record["source"].pop("retrieval_allowed")
    return json.dumps(record, ensure_ascii=False)


def paste_and_preview(app: AppTest, content: str) -> None:
    app.radio(key="kb_input_mode").set_value("粘贴内容").run()
    app.text_area(key="kb_paste_content").set_value(content).run()
    assert not app.button(key="kb_validate").disabled
    app.button(key="kb_validate").click().run()
    assert not app.exception


def confirm_and_import(app: AppTest) -> None:
    assert not app.checkbox(key="kb_confirm").disabled
    assert app.button(key="kb_commit").disabled
    app.checkbox(key="kb_confirm").check().run()
    assert not app.button(key="kb_commit").disabled
    app.button(key="kb_commit").click().run()
    assert not app.exception


def assert_preview_cleared(app: AppTest) -> None:
    assert not app.exception
    assert "kb_preview" not in app.session_state
    assert "kb_preview_input" not in app.session_state
    assert not any(item.key == "kb_commit" for item in app.button)
    assert not any(item.key == "kb_confirm" for item in app.checkbox)
    if "kb_confirm" in app.session_state:
        assert app.session_state["kb_confirm"] is False


def test_empty_workbench_starts_without_cloud_credentials(workbench) -> None:
    app, store = workbench
    assert app.radio(key="kb_input_mode").value == "上传文件"
    assert app.button(key="kb_validate").disabled
    assert [tab.label for tab in app.tabs] == ["导入工作台", "知识条目", "操作记录"]
    assert len(store.list_libraries()) == 6
    assert store.list_revisions() == []
    assert store.audit_log() == []
    assert any("还没有知识版本" in item.value for item in app.info)


def test_example_preview_is_read_only_and_cannot_be_imported(workbench) -> None:
    app, store = workbench
    app.button(key="kb_example").click().run()
    assert not app.exception
    assert app.session_state["kb_preview_example"] is True
    assert len(app.session_state["kb_preview"].records) == 1
    assert app.checkbox(key="kb_confirm").disabled
    assert app.button(key="kb_commit").disabled
    assert any("只读示例" in item.value for item in app.info)
    app.run()
    assert store.list_revisions() == []
    assert store.audit_log() == []


def test_paste_preview_and_confirm_save_only_unlicensed_draft(workbench) -> None:
    app, store = workbench
    paste_and_preview(app, record_json())
    assert app.session_state["kb_preview_example"] is False
    assert app.checkbox(key="kb_confirm").value is False
    assert store.list_revisions() == []
    confirm_and_import(app)

    revisions = store.list_revisions()
    assert len(revisions) == 1
    assert revisions[0].status == "draft"
    assert revisions[0].record.source.retrieval_allowed is False
    assert [entry["action"] for entry in store.audit_log()] == ["save_draft"]
    assert any("新增 1 个草稿版本" in item.value for item in app.success)
    assert "kb_preview" not in app.session_state


def test_invalid_json_disables_confirmation_and_never_writes(workbench) -> None:
    app, store = workbench
    paste_and_preview(app, '{"knowledge_id": invalid-json}')
    assert app.error
    assert app.session_state["kb_preview"].issues
    assert app.checkbox(key="kb_confirm").disabled
    assert app.button(key="kb_commit").disabled
    assert store.list_revisions() == []
    assert store.audit_log() == []


def test_changing_pasted_content_revokes_preview_and_confirmation(workbench) -> None:
    app, store = workbench
    paste_and_preview(app, record_json())
    app.checkbox(key="kb_confirm").check().run()
    assert not app.button(key="kb_commit").disabled
    app.text_area(key="kb_paste_content").set_value(record_json("ui-new-record-002")).run()
    assert_preview_cleared(app)
    assert store.list_revisions() == []

    app.button(key="kb_validate").click().run()
    assert app.checkbox(key="kb_confirm").value is False
    assert app.button(key="kb_commit").disabled


def test_changing_input_mode_revokes_preview_and_confirmation(workbench) -> None:
    app, store = workbench
    paste_and_preview(app, record_json())
    app.checkbox(key="kb_confirm").check().run()
    app.radio(key="kb_input_mode").set_value("上传文件").run()
    assert_preview_cleared(app)
    assert app.button(key="kb_validate").disabled
    assert store.list_revisions() == []


def test_changing_paste_format_revokes_preview(workbench) -> None:
    app, store = workbench
    paste_and_preview(app, record_json())
    app.checkbox(key="kb_confirm").check().run()
    app.selectbox(key="kb_paste_format").select("YAML").run()
    assert_preview_cleared(app)
    assert store.audit_log() == []


def test_repeated_import_is_idempotent_and_reports_existing_version(workbench) -> None:
    app, store = workbench
    paste_and_preview(app, record_json())
    confirm_and_import(app)
    original_audit = store.audit_log()

    app.button(key="kb_validate").click().run()
    confirm_and_import(app)
    assert len(store.list_revisions()) == 1
    assert store.audit_log() == original_audit
    assert any("新增 0 个草稿版本" in item.value for item in app.success)
    assert any("1 个相同版本已存在" in item.value for item in app.success)


def test_record_and_audit_filters_are_read_only(workbench) -> None:
    app, store = workbench
    paste_and_preview(app, record_json())
    confirm_and_import(app)
    original_audit = store.audit_log()
    assert len(app.dataframe) == 2
    assert app.dataframe[0].value.iloc[0]["知识编号"] == "ui-composition-001"
    assert app.dataframe[0].value.iloc[0]["状态"] == "草稿"
    assert app.dataframe[1].value.iloc[0]["操作"] == "保存草稿"

    app.selectbox(key="kb_status_filter").select("已发布").run()
    assert any("还没有知识版本" in item.value for item in app.info)
    app.selectbox(key="kb_status_filter").select("草稿").run()
    assert app.selectbox(key="kb_record_detail").value == 0
    app.radio(key="kb_scope").set_value("equipment").run()
    assert len(app.dataframe) == 0
    app.radio(key="kb_scope").set_value("composition").run()
    assert len(app.dataframe) == 2
    assert store.audit_log() == original_audit
    assert store.list_revisions()[0].status == "draft"
    assert not any(button.label in {"发布", "审核通过", "提交审核"} for button in app.button)
    assert not app.exception


@dataclass
class FakeUploadedFile:
    name: str
    data: bytes

    def getvalue(self) -> bytes:
        return self.data


def test_mixed_uploaded_batch_with_invalid_file_is_not_partially_imported(
    workbench, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, store = workbench
    files = [
        FakeUploadedFile("valid.json", record_json().encode("utf-8")),
        FakeUploadedFile("invalid.json", b"{not-json}"),
    ]
    # AppTest不提供上传操作，用文件上传控件的返回值替身覆盖混合批次路径。
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: files)
    app.run()
    app.button(key="kb_validate").click().run()
    preview = app.session_state["kb_preview"]
    assert preview.total_files == 2
    assert len(preview.records) == 1
    assert len(preview.issues) == 1
    assert app.checkbox(key="kb_confirm").disabled
    assert app.button(key="kb_commit").disabled
    assert store.list_revisions() == []
    assert store.audit_log() == []
    assert not app.exception


def test_valid_uploaded_batch_saves_each_files_declared_library(
    workbench, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, store = workbench
    files = [
        FakeUploadedFile("composition.json", record_json().encode("utf-8")),
        FakeUploadedFile(
            "equipment.json", record_json("ui-equipment-002", "equipment").encode("utf-8")
        ),
    ]
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: files)
    app.radio(key="kb_scope").set_value("technique").run()
    app.button(key="kb_validate").click().run()
    assert len(app.session_state["kb_preview"].records) == 2
    assert store.list_revisions() == []
    confirm_and_import(app)
    revisions = store.list_revisions()
    assert {item.record.library_id for item in revisions} == {"composition", "equipment"}
    assert {item.status for item in revisions} == {"draft"}
    assert all(not item.record.source.retrieval_allowed for item in revisions)
    assert len(store.audit_log()) == 2
    assert any("新增 2 个草稿版本" in item.value for item in app.success)


def test_oversized_upload_is_rejected_before_import(
    workbench, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, store = workbench
    files = [FakeUploadedFile("too-large.json", b" " * (MAX_UPLOAD_BYTES + 1))]
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: files)
    app.run()
    app.button(key="kb_validate").click().run()
    preview = app.session_state["kb_preview"]
    assert preview.records == []
    assert any("2 MiB" in issue.message for issue in preview.issues)
    assert app.checkbox(key="kb_confirm").disabled
    assert app.button(key="kb_commit").disabled
    assert store.list_revisions() == []
    assert store.audit_log() == []
    assert not app.exception
