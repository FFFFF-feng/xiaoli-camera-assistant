"""独立、本地使用的知识库导入工作台；上传资料只保存为草稿。"""

from __future__ import annotations

import html
import inspect
import sqlite3
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import streamlit as st

from camera_assistant.config import PROJECT_ROOT, Settings
from camera_assistant.knowledge.models import DEFAULT_LIBRARIES, KnowledgeRecord, LibraryId
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.knowledge.ui_helpers import (
    ACTION_LABELS,
    KIND_LABELS,
    STATUS_LABELS,
    assistant_web_url,
    template_json,
)
from camera_assistant.knowledge.uploads import (
    MAX_BATCH_BYTES,
    MAX_BATCH_FILES,
    MAX_UPLOAD_BYTES,
    PreviewBatch,
    UploadedRecordFile,
    commit_preview,
    preview_uploads,
    uploads_fingerprint,
)

LIBRARY_NAMES = {library.library_id: library.name for library in DEFAULT_LIBRARIES}
ASSETS = Path(__file__).resolve().parent / "assets"


def section(number: str, title: str, note: str = "") -> None:
    st.markdown(
        f'<div class="kb-section"><span>{html.escape(number)}</span>'
        f"<div><h3>{html.escape(title)}</h3><p>{html.escape(note)}</p></div></div>",
        unsafe_allow_html=True,
    )


def show_record(record: KnowledgeRecord) -> None:
    st.caption(
        f"{LIBRARY_NAMES[record.library_id]} · {KIND_LABELS[record.kind]} · "
        f"{record.knowledge_id} / v{record.version}"
    )
    st.text(record.title)
    if record.content:
        st.text(record.content)
    if record.tags:
        st.caption("标签：" + " / ".join(record.tags))
    with st.expander("来源、适用条件与完整字段"):
        st.json(record.model_dump(mode="json"), expanded=False)


def save_preview(preview: PreviewBatch, input_fingerprint: str, *, example: bool) -> None:
    st.session_state["kb_preview"] = preview
    st.session_state["kb_preview_input"] = input_fingerprint
    st.session_state["kb_preview_example"] = example
    st.session_state["kb_confirm"] = False
    st.session_state.pop("kb_import_feedback", None)


def read_inputs() -> list[UploadedRecordFile]:
    mode = st.radio("资料输入方式", ["上传文件", "粘贴内容"], horizontal=True, key="kb_input_mode")
    if mode == "上传文件":
        # 新版支持控件级限制；旧版仍由上传桥接执行相同的硬性校验。
        size_options = (
            {"max_upload_size": MAX_UPLOAD_BYTES // (1024 * 1024)}
            if "max_upload_size" in inspect.signature(st.file_uploader).parameters
            else {}
        )
        uploaded = st.file_uploader(
            "选择整理好的知识文件",
            type=["json", "yaml", "yml", "md"],
            accept_multiple_files=True,
            key="kb_files",
            help="一文件一条知识；Markdown需要YAML front matter。普通PDF、图片不直接导入。",
            **size_options,
        )
        st.caption(
            f"JSON / YAML / Markdown · 单文件 ≤ {MAX_UPLOAD_BYTES // (1024 * 1024)} MB · "
            f"最多 {MAX_BATCH_FILES} 个 · 总计 ≤ {MAX_BATCH_BYTES // (1024 * 1024)} MB"
        )
        return [UploadedRecordFile(item.name, item.getvalue()) for item in uploaded]

    format_name = st.selectbox("内容格式", ["JSON", "YAML", "Markdown"], key="kb_paste_format")
    content = st.text_area(
        "粘贴一条完整知识记录",
        height=220,
        placeholder='例如：{"knowledge_id": "composition-001", "library_id": "composition", ...}',
        key="kb_paste_content",
        help="字段与文件模板一致。支持JSON、YAML和带front matter的Markdown，不支持纯文章自动整理。",
    )
    extension = {"JSON": "json", "YAML": "yaml", "Markdown": "md"}[format_name]
    return (
        [UploadedRecordFile(f"pasted-record.{extension}", content.encode("utf-8"))]
        if content.strip()
        else []
    )


def render_preview(store: KnowledgeStore, input_fingerprint: str) -> None:
    section("02", "检查后再入库", "字段校验是第一关，内容准确性仍需要队员审核。")
    if st.button("先看看示例效果", key="kb_example", use_container_width=True):
        sample = UploadedRecordFile("example-composition.json", template_json().encode("utf-8"))
        save_preview(preview_uploads([sample]), input_fingerprint, example=True)

    preview: PreviewBatch | None = st.session_state.get("kb_preview")
    if preview is None:
        st.markdown(
            '<div class="kb-empty-preview"><span class="kb-empty-icon">◎</span>'
            "<h3>好知识，值得先检查</h3><p>上传资料并点击「校验并预览」，<br>这里会显示条目、来源和检查结果。</p>"
            '<div class="kb-checklist">01　字段与格式<br>02　知识编号与版本<br>03　来源与检索许可</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        return

    is_example = st.session_state.get("kb_preview_example", False)
    if is_example:
        st.info("只读示例，不会写入数据库。请用你们整理的真实资料进行导入。", icon="🔎")
    if preview.issues:
        st.error(f"发现 {len(preview.issues)} 项问题，整批资料暂不允许导入。")
        for issue in preview.issues:
            # 用户控制的文件名不得作为HTML或Markdown解释。
            st.text(f"{issue.file}：{issue.message}")
    else:
        st.success(f"格式检查通过 · {len(preview.records)} 条记录", icon="✅")

    if preview.records:
        st.dataframe(
            [
                {
                    "标题": record.title,
                    "所属知识库": LIBRARY_NAMES[record.library_id],
                    "版本": f"v{record.version}",
                    "允许检索": "是（仍需审核发布）" if record.source.retrieval_allowed else "否",
                }
                for record in preview.records
            ],
            hide_index=True,
            use_container_width=True,
        )
        record_index = st.selectbox(
            "查看条目详情",
            range(len(preview.records)),
            format_func=lambda index: (
                f"{preview.records[index].knowledge_id} / v{preview.records[index].version}"
            ),
            key=f"kb_preview_detail_{preview.fingerprint}",
        )
        with st.expander("展开正文和来源", expanded=False):
            show_record(preview.records[record_index])

    valid = (
        preview.success
        and bool(preview.records)
        and not is_example
        and st.session_state.get("kb_preview_input") == input_fingerprint
    )
    confirmed = st.checkbox(
        "我已检查以上内容，按草稿保存",
        key="kb_confirm",
        disabled=not valid,
    )
    st.caption("导入不等于发布。草稿不会参与相机建议检索；审核和发布继续使用命令行流程。")
    if st.button(
        "导入为草稿",
        type="primary",
        disabled=not (valid and confirmed),
        use_container_width=True,
        key="kb_commit",
    ):
        with st.spinner("正在原子保存这批资料…"):
            report = commit_preview(store, preview)
        if report.success:
            st.session_state["kb_import_feedback"] = (
                f"导入完成：新增 {report.imported_count} 个草稿版本，"
                f"{report.unchanged_count} 个相同版本已存在，未重复写入。"
            )
            st.session_state.pop("kb_preview", None)
            st.session_state.pop("kb_preview_input", None)
            st.rerun()
        else:
            st.error("保存失败，整批未写入。请检查编号、版本及现有记录。")
            for issue in report.errors:
                st.text(f"{issue.file}：{issue.message}")


def render_import(store: KnowledgeStore, selected_library: LibraryId | None) -> None:
    feedback = st.session_state.get("kb_import_feedback")
    if feedback:
        st.success(feedback, icon="✅")
    left, right = st.columns([1.08, 1], gap="large")
    with left:
        section("01", "带来整理好的资料", "先选输入方式，再校验；不会自动修改资料的所属库。")
        files = read_inputs()
        # 模式变化（含空内容）也撤销旧确认，不能沿用另一个输入的预览。
        fingerprint = (
            st.session_state["kb_input_mode"]
            + ":"
            + uploads_fingerprint(files)
            + ":"
            + str(st.session_state.get("kb_paste_format", ""))
        )
        if st.session_state.get("kb_preview_input") not in (None, fingerprint):
            st.session_state.pop("kb_preview", None)
            st.session_state.pop("kb_preview_input", None)
            st.session_state["kb_confirm"] = False
            st.session_state.pop("kb_import_feedback", None)
            st.caption("输入已变化，请重新校验预览。")
        if st.button(
            "校验并预览",
            type="primary",
            disabled=not files,
            use_container_width=True,
            key="kb_validate",
        ):
            with st.spinner("正在检查字段、来源和批次冲突…"):
                preview = preview_uploads(files)
            save_preview(preview, fingerprint, example=False)
        st.markdown(
            '<div class="kb-template-heading">还没有标准文件？从模板开始</div>',
            unsafe_allow_html=True,
        )
        template_library = st.selectbox(
            "模板所属知识库",
            list(LIBRARY_NAMES),
            index=list(LIBRARY_NAMES).index(selected_library or "composition"),
            format_func=LIBRARY_NAMES.get,
            key="kb_template_library",
        )
        st.download_button(
            "下载 JSON 模板",
            data=template_json(template_library),
            file_name=f"{template_library}-template.json",
            mime="application/json",
            use_container_width=True,
            key="kb_download_template",
        )
        with st.expander("导入格式小贴士"):
            st.markdown(
                "- 一个文件对应一条记录，多个文件一起原子导入。\n"
                "- 必填编号、所属库、标题、类型、来源、作者；正文或结构化数据至少一项非空。\n"
                "- 相同编号和版本不允许换内容；修改内容请增加版本号。\n"
                "- 来源未获授权时保留 `retrieval_allowed: false`。\n"
                "- PDF、图片、普通文章需由整理队员先转换为标准记录。"
            )
        starter_dir = PROJECT_ROOT / "data/knowledge_drafts/starter-v1"
        starter_files = sorted(starter_dir.glob("*.md"))
        if starter_files:
            archive = BytesIO()
            with ZipFile(archive, "w") as zipped:
                for file in starter_files:
                    zipped.writestr(file.name, file.read_bytes())
            st.download_button(
                f"下载首批 {len(starter_files)} 条规则草稿",
                data=archive.getvalue(),
                file_name="xiaoli-knowledge-starter-v1.zip",
                mime="application/zip",
                use_container_width=True,
                key="kb_download_starter",
            )
            st.caption("先解压，再上传MD文件；全部待人工审核，厂商来源的许可还需核验。")
    with right:
        render_preview(store, fingerprint)


def render_records(store: KnowledgeStore, selected_library: LibraryId | None) -> None:
    section("阅", "知识条目", "只读查看全部版本；左侧选择知识库可缩小范围。")
    status_name = st.selectbox(
        "审核状态", ["全部状态", *STATUS_LABELS.values()], key="kb_status_filter"
    )
    status = next((key for key, value in STATUS_LABELS.items() if value == status_name), None)
    revisions = store.list_revisions(library_id=selected_library, status=status)
    if not revisions:
        st.info("当前范围还没有知识版本。到「导入工作台」添加第一批草稿吧。", icon="📂")
        return
    st.caption(f"共 {len(revisions)} 个版本（同一编号的不同版本分别计数）")
    st.dataframe(
        [
            {
                "知识编号": revision.record.knowledge_id,
                "标题": revision.record.title,
                "所属知识库": LIBRARY_NAMES[revision.record.library_id],
                "版本": revision.record.version,
                "状态": STATUS_LABELS[revision.status],
                "整理者": revision.record.author,
            }
            for revision in revisions
        ],
        hide_index=True,
        use_container_width=True,
    )
    index = st.selectbox(
        "选择知识版本",
        range(len(revisions)),
        format_func=lambda item: (
            f"{revisions[item].record.knowledge_id} / v{revisions[item].record.version}"
        ),
        key="kb_record_detail",
    )
    show_record(revisions[index].record)
    st.caption(f"当前状态：{STATUS_LABELS[revisions[index].status]} · 页面不提供审核或发布操作")


def render_audit(store: KnowledgeStore, selected_library: LibraryId | None) -> None:
    section("迹", "操作记录", "真实数据库审计，不包含尚未保存的预览。时间显示为 UTC。")
    entries = store.audit_log()
    if selected_library is not None:
        record_ids = {item.record.knowledge_id for item in store.list_revisions(selected_library)}
        entries = [entry for entry in entries if entry["knowledge_id"] in record_ids]
    if not entries:
        st.info("还没有保存或审核操作；示例预览不会产生审计记录。", icon="🕒")
        return
    st.caption(f"共 {len(entries)} 条操作记录，以下展示最近 200 条")
    st.dataframe(
        [
            {
                "时间（UTC）": entry["occurred_at"],
                "操作": ACTION_LABELS.get(entry["action"], entry["action"]),
                "知识编号": entry["knowledge_id"],
                "版本": entry["version"],
                "操作者": entry["actor"] or "—",
            }
            for entry in entries[-200:][::-1]
        ],
        hide_index=True,
        use_container_width=True,
    )


def main() -> None:
    st.set_page_config(page_title="小栗 · 知识工作台", page_icon="📚", layout="wide")
    st.markdown(
        f"<style>{(ASSETS / 'knowledge.css').read_text(encoding='utf-8')}</style>",
        unsafe_allow_html=True,
    )
    try:
        settings = Settings.from_env()
        store = KnowledgeStore(settings.knowledge_db_path or PROJECT_ROOT / "data/knowledge.db")
        counts = store.library_counts()
    except (ValueError, OSError, sqlite3.Error):
        st.error("知识库暂不可用，请检查 KNOWLEDGE_DB_PATH 配置、文件权限和数据库版本。")
        st.stop()

    with st.sidebar:
        st.image(str(ASSETS / "camera-red-panda.png"), width=105)
        st.markdown(
            '<div class="kb-brand">小栗<span>知识工作台</span></div>', unsafe_allow_html=True
        )
        st.caption("把可靠的知识，交给取景参谋。")
        st.caption("存储：SQLite · " + store.db_path.name)
        st.divider()
        scope = st.radio(
            "知识库范围",
            ["all", *LIBRARY_NAMES],
            format_func=lambda library: (
                "全部知识库"
                if library == "all"
                else f"{LIBRARY_NAMES[library]} · {sum(counts[library].values())}"
            ),
            key="kb_scope",
        )
        st.caption("范围只筛选浏览内容。导入归属由文件中的 library_id 决定。")
        st.divider()
        st.markdown("**先草稿，再互审**")
        st.caption("资料整理 → 校验导入 → 提交审核 → 队友互审 → 发布检索")
        st.caption(
            "摄影助手检索："
            + (
                "受管知识库"
                if settings.knowledge_mode == "managed"
                else "旧版演示库（尚未开启 managed）"
            )
        )
        st.link_button("打开取景参谋 ↗", assistant_web_url(PROJECT_ROOT), use_container_width=True)
        st.caption("仅限本机 / 可信团队使用。尚无登录鉴权，不要直接开放公网。")

    selected_library: LibraryId | None = None if scope == "all" else scope
    summary = {
        status: sum(library[status] for library in counts.values()) for status in STATUS_LABELS
    }
    st.markdown(
        '<div class="kb-heading"><div class="kb-eyebrow">XIAOLI / KNOWLEDGE STUDIO</div>'
        "<h1>给小栗，装进口袋的知识。</h1>"
        "<p>六类知识，一个工作台。从队员整理的资料，到可追溯的草稿版本。</p>"
        '<span class="kb-local-badge">● 本地知识库 · 只导入草稿</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="kb-stats"><div><strong>{len(counts):02d}</strong><span>已注册知识库</span></div>'
        f"<div><strong>{sum(summary.values()):02d}</strong><span>知识版本</span></div>"
        f"<div><strong>{summary['draft']:02d}</strong><span>待完善草稿</span></div>"
        f"<div><strong>{summary['published']:02d}</strong><span>已发布版本</span></div></div>",
        unsafe_allow_html=True,
    )
    imports, records, audit = st.tabs(["导入工作台", "知识条目", "操作记录"])
    with imports:
        render_import(store, selected_library)
    with records:
        render_records(store, selected_library)
    with audit:
        render_audit(store, selected_library)
    st.markdown(
        '<div class="kb-footer">小栗知识工作台 · 校验格式，不替代事实核查与实拍验证</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
