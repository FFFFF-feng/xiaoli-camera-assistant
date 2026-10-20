"""Prepare a small licensed release; publication requires an explicit reviewed manifest hash."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from camera_assistant.knowledge.models import KnowledgeRecord
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeStore

LICENSE = "https://creativecommons.org/licenses/by-sa/4.0/"
COMPOSITION_URL = "https://en.wikibooks.org/w/index.php?title=Modern_Photography/Composition&oldid=3831538"
EXISTING = (
    "technique-blur-diagnosis-001", "technique-digital-crop-001",
    "technique-exposure-clipping-001", "technique-shutter-motion-001", "technique-white-balance-001",
)
COMPOSITION = (
    ("thirds", "三分法与居中方案比较", "三分法 构图 主体 九宫格",
     "可比较主体靠近三分交点与居中的取景；三分法不是强制评分规则。", "Rule of Thirds / Common criticisms"),
    ("background", "检查主体与背景重叠", "背景 干扰 人像 杆线 主体",
     "检查背景杆线是否与主体重叠；安全允许时换机位比较，不盲目删除环境信息。", "Avoiding mergers / Distracting backgrounds"),
    ("framing", "用现场前景组织框架", "前景 框架 门窗 树枝 构图",
     "可利用实际存在的门窗、枝叶形成框架；先检查是否遮住需要展示的主体部分。", "Framing"),
    ("depth", "保留前景与环境层次", "空间 层次 前景 中景 背景 风景",
     "可用现场前景表达空间层次；不凭空添加物体，也不保证加入前景一定更好。", "Lack of depth"),
    ("balance", "比较对称与视觉平衡", "对称 居中 颜色 明暗 平衡 建筑",
     "比较两侧元素的大小、颜色与明暗；对称可以成立，不必为了三分法强行偏置。", "Color and tone / Symmetry and balance"),
    ("format", "先明确画幅与保留范围", "画幅 横构图 竖构图 裁切 边界",
     "先比较横竖画幅及必须保留的内容；裁切只能利用原图范围，不能补回画外现场。", "Format"),
    ("subject-size", "比较主体占比与环境信息", "主体 占比 留白 取景 人像 环境",
     "可比较主体更大的取景与环境版本；保留叙事需要的背景，不设统一人物占比。", "Too far / Common criticisms"),
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def notice(source):
    return (f"\n\n出处：{source.name}；{source.url}。"
            f"中文摘要及保守适用边界为改写；CC BY-SA 4.0：{LICENSE}。未使用来源图片。")


def prepare(database, output):
    store = KnowledgeStore(database)
    records, bases = [], {}
    for identity in EXISTING:
        previous = store.get_revision(identity)
        if previous is None or not previous.record.source.retrieval_allowed:
            raise ValueError("expected_open_licensed_base_missing")
        bases[identity] = {"version": previous.record.version, "content_hash": previous.content_hash}
        record = previous.record.model_copy(deep=True)
        record.version += 1
        record.content += notice(record.source)
        record.payload["verification"] = {"status": "source_checked_release_candidate",
            "checked_at": "2026-10-19", "human_expert_review": False, "field_tested": False,
            "scope": "基础原理核对；不包含固定曝光值或机型能力保证。"}
        records.append(record)
    for suffix, title, tags, content, location in COMPOSITION:
        record = KnowledgeRecord.model_validate({
            "knowledge_id": "online-cc-composition-" + suffix, "version": 1,
            "library_id": "composition", "kind": "guideline", "title": title,
            "content": content, "tags": tags.split(), "conditions": {},
            "author": "Codex 中文资料整理", "dataset_split": "reference",
            "source": {"name": "Wikibooks contributors / Modern Photography / Composition",
                "url": COMPOSITION_URL, "location": location,
                "license": "CC BY-SA 4.0；中文摘要同许可，署名及改写说明见正文；不含图片。",
                "retrieval_allowed": True},
            "payload": {"automatic_execution": False, "numeric_default": None,
                "verification": {"checked_at": "2026-10-19", "status": "source_checked_release_candidate",
                    "human_expert_review": False, "field_tested": False}},
        })
        record.content += notice(record.source)
        records.append(record)
    manifest = {"schema_version": 1, "release_id": "online-baseline-20261019",
        "scope": "12条基础规则；其余草稿不解锁。不证明实拍效果或机型兼容性。",
        "base_revisions": bases, "records": [r.model_dump(mode="json") for r in records]}
    output.mkdir(parents=True, exist_ok=False)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    sections = "".join(f"<section><h2>{html.escape(r.title)}</h2><p>{html.escape(r.content)}</p>"
                       f"<small>{html.escape(r.library_id)} · {html.escape(r.knowledge_id)} / v{r.version}</small></section>"
                       for r in records)
    page = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>首批上线知识确认</title>'
            '<style>body{max-width:900px;margin:40px auto;padding:0 24px;font:17px/1.8 sans-serif;color:#193b35}'
            'section{border-top:1px solid #cddbd4;padding:16px 0}p{white-space:pre-wrap;overflow-wrap:anywhere}'
            'small{color:#63766d}h2{font-size:20px}</style><h1>首批12条上线知识确认</h1>'
            '<p>以下仅做基础原理与许可来源核对，未经过独立专家审核或实拍验证。'
            '拟用于手机/相机的通用建议；其余器材与测试草稿不启用。确认后才发布。</p>' + sections + '</html>')
    (output / "review.html").write_text(page, encoding="utf-8")
    print(json.dumps({"release_digest": digest(manifest), "records": len(records), "output": str(output)}))
    return manifest


def publish(database, manifest_path, reviewer, confirmation_hash, report_dir):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or digest(manifest) != confirmation_hash:
        raise ValueError("release_confirmation_hash_mismatch")
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("explicit_reviewer_required")
    records = [KnowledgeRecord.model_validate(r) for r in manifest["records"]]
    if not records or len(records) > 100:
        raise ValueError("release_record_count_invalid")
    if any(not r.source.retrieval_allowed or r.dataset_split != "reference" for r in records):
        raise ValueError("release_contains_unpermitted_record")
    if any(r.author.casefold() == reviewer.casefold() for r in records):
        raise ValueError("author_cannot_review_own_release")
    store = KnowledgeStore(database)
    for identity, base in manifest["base_revisions"].items():
        old = store.get_revision(identity, base["version"])
        if old is None or old.content_hash != base["content_hash"]:
            raise ValueError("reviewed_base_changed")
    for record in records:
        existing = store.get_revision(record.knowledge_id, record.version)
        latest = store.get_revision(record.knowledge_id)
        if existing and existing.content_hash != digest(record.model_dump(mode="json")):
            raise ValueError("release_revision_conflict")
        if latest and latest.record.version > record.version:
            raise ValueError("newer_revision_exists")
        if existing and existing.status not in {"draft", "pending_review", "approved", "published"}:
            raise ValueError("release_revision_not_publishable")
    report_dir.mkdir(parents=True, exist_ok=False)
    with (closing(sqlite3.connect(database.resolve().as_uri()+"?mode=ro", uri=True)) as source,
          closing(sqlite3.connect(report_dir/"before-publish.db")) as backup):
        source.backup(backup)
    (report_dir/"before-publish.db").chmod(0o600)
    note = ("用户按已展示的12条清单确认发布；来源及许可由AI核对，"
            "不代表独立专家审核、实拍验证或制造商认证。release=" + confirmation_hash)
    for record in records:
        revision = store.save_draft(record)
        if revision.status == "draft":
            revision = store.submit(record.knowledge_id, record.version)
        if revision.status == "pending_review":
            revision = store.approve(record.knowledge_id, reviewer, record.version, note)
        if revision.status == "approved":
            store.publish(record.knowledge_id, record.version)
    retriever = ManagedKnowledgeRetriever(store)
    checks = {}
    for device in ("phone", "camera"):
        parameter = retriever.search("夜景 手持 模糊 对焦 曝光 白平衡 快门", libraries=["scene", "technique", "equipment"],
                                     conditions={"device_type": device, "motion": "fast"})
        composition = retriever.search("构图 主体 三分法 背景 前景 层次", libraries=["composition", "style", "case"],
                                       conditions={"device_type": device})
        if not parameter or not composition:
            raise ValueError("released_knowledge_route_empty")
        checks[device] = {"parameter_ids": [h.document_id for h in parameter],
                          "composition_ids": [h.document_id for h in composition]}
    result = {"release_id": manifest["release_id"], "release_digest": confirmation_hash,
        "published_release_records": len(records), "reviewer": reviewer,
        "expert_reviewed": False, "field_tested": False, "checks": checks,
        "completed_at": datetime.now(UTC).isoformat(), "counts": store.library_counts()}
    (report_dir/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "publish"])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--reviewer")
    parser.add_argument("--confirmation-sha256")
    args = parser.parse_args()
    if not args.output:
        parser.error("--output is required")
    if args.operation == "prepare":
        prepare(args.db, args.output)
    else:
        if not all((args.manifest, args.reviewer, args.confirmation_sha256)):
            parser.error("publication requires --manifest, --reviewer, --confirmation-sha256")
        publish(args.db, args.manifest, args.reviewer, args.confirmation_sha256, args.output)


if __name__ == "__main__":
    main()
