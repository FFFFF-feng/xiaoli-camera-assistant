"""导入工作台的展示词汇与安全模板，不包含正式摄影知识。"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from camera_assistant.knowledge.models import KnowledgeRecord, LibraryId, SourceInfo

STATUS_LABELS = {
    "draft": "草稿",
    "pending_review": "待审核",
    "needs_revision": "待修改",
    "approved": "已审核",
    "published": "已发布",
    "retired": "已退役",
}
KIND_LABELS = {
    "manufacturer_fact": "厂商事实",
    "guideline": "经验指引",
    "observed_case": "实拍案例",
}
ACTION_LABELS = {
    "save_draft": "保存草稿",
    "submit": "提交审核",
    "approve": "审核通过",
    "reject": "退回修改",
    "publish": "发布",
    "retire": "退役",
}


def _launcher_port(state: Path, project_root: Path, project_key: str) -> int | None:
    if state.stat().st_size > 16 * 1024:
        return None
    data = json.loads(state.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    project = data.get(project_key)
    if not isinstance(project, str) or Path(project).resolve() != project_root.resolve():
        return None
    port = data.get("port")
    if type(port) is int and 1024 <= port <= 65535:
        return port
    url = data.get("url")
    if isinstance(url, str):
        parsed = urlsplit(url)
        if (parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
                and not parsed.username and not parsed.password
                and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment
                and parsed.port is not None and 1024 <= parsed.port <= 65535):
            return parsed.port
    return None


def assistant_web_url(project_root: Path) -> str:
    """Use this project's current local launcher port, never an arbitrary URL."""
    for name, key in (("web-service.json", "project"), ("web-start.json", "project_root")):
        try:
            port = _launcher_port(project_root / ".launcher" / name, project_root, key)
        except (OSError, ValueError, TypeError):
            continue
        if port is not None:
            return f"http://127.0.0.1:{port}/"
    return "http://localhost:8501/"


def template_record(library_id: LibraryId = "composition") -> KnowledgeRecord:
    """提供可校验的占位记录，权限默认关闭，不能作为正式推荐依据。"""
    return KnowledgeRecord(
        knowledge_id=f"template-{library_id}-001",
        library_id=library_id,
        title="示例模板｜请替换为已核对的知识标题",
        kind="guideline",
        content=(
            "这是一份导入格式示例，不是正式摄影知识。\n"
            "请填写适用场景、操作建议、限制与例外，并核对来源和授权后再提交审核。"
        ),
        payload={},
        tags=["模板示例"],
        conditions={},
        source=SourceInfo(
            name="请填写真实来源名称",
            location="请填写章节、页码或段落",
            license="请填写已核对的授权说明",
            retrieval_allowed=False,
        ),
        author="请填写整理者姓名",
    )


def template_json(library_id: LibraryId = "composition") -> str:
    return json.dumps(
        template_record(library_id).model_dump(mode="json"), ensure_ascii=False, indent=2
    )
