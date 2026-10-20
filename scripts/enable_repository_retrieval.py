"""用户明确授权后批量发布正式资料；不伪称准确性、许可或专家核验。"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from camera_assistant.knowledge.store import KnowledgeStore

RELEASE = "user-enabled-reference-20261019"
WARNING = ("发布说明：用户要求暂不逐条核验，批量启用检索。未经独立专家或实拍验证；"
           "来源许可说明按原记录保留，启用不代表取得第三方额外授权。"
           "器材记录仅作参考，不自动覆盖硬件能力或曝光限制。")


def enable(database: Path, output: Path, actor: str, *, confirmed: bool = False):
    if not confirmed:
        raise ValueError("explicit_bulk_confirmation_required")
    actor = actor.strip()
    if not actor or len(actor) > 128:
        raise ValueError("explicit_actor_required")
    if not database.is_file():
        raise ValueError("existing_database_required")
    store = KnowledgeStore(database)
    # 只列标识，避免将整库记录及其历史版本一起载入内存。
    with closing(sqlite3.connect(database)) as connection:
        identities = [row[0] for row in connection.execute(
            "SELECT DISTINCT knowledge_id FROM revisions ORDER BY knowledge_id")]
    for identity in identities:
        revision = store.get_revision(identity)
        if revision.record.dataset_split == "reference" and revision.record.author.casefold() == actor.casefold():
            raise ValueError("author_cannot_approve_own_record")
    output.mkdir(parents=True, exist_ok=False)
    with (closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as source,
          closing(sqlite3.connect(output / "before-enable.db")) as backup):
        source.backup(backup)
    (output / "before-enable.db").chmod(0o600)
    added = skipped = evaluation = 0
    for identity in identities:
        revision = store.get_revision(identity)
        record = revision.record
        if record.dataset_split != "reference":
            evaluation += 1
            continue
        if revision.status == "published":
            skipped += 1
            continue
        marker = record.payload.get("retrieval_release", {})
        if marker.get("release_id") != RELEASE:
            record = record.model_copy(deep=True)
            record.version += 1
            previous_permission = record.source.retrieval_allowed
            record.source.retrieval_allowed = True
            # 保留原核验结果及原许可，不把用户启用决定当成事实验证。
            record.payload["retrieval_release"] = {
                "release_id": RELEASE, "actor": actor,
                "decision": "user_authorized_without_accuracy_review",
                "previous_retrieval_allowed": previous_permission,
                "expert_reviewed": False, "field_tested": False,
                "license_independently_cleared": False,
                "controls_hardware_limits": False,
            }
            record.content += (f"\n\n{WARNING}\n出处：{record.source.name}；"
                               f"{record.source.url or '未提供链接'}。原许可说明：{record.source.license or '未提供'}。")
            revision = store.save_draft(record)
        if revision.status == "draft":
            revision = store.submit(identity, record.version)
        if revision.status == "pending_review":
            revision = store.approve(identity, actor, record.version, WARNING)
        if revision.status == "approved":
            revision = store.publish(identity, record.version)
        if revision.status != "published":
            raise ValueError(f"release_incomplete:{identity}:{revision.status}")
        added += 1
        if added % 500 == 0:
            print(f"enabled={added}", flush=True)
    with closing(sqlite3.connect(database)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        bad = connection.execute("SELECT COUNT(*) FROM revisions WHERE status='published' "
            "AND (json_extract(record_json,'$.dataset_split')!='reference' "
            "OR json_extract(record_json,'$.source.retrieval_allowed')!=1)").fetchone()[0]
    if integrity != "ok" or bad:
        raise ValueError("post_release_integrity_failure")
    result = {"release_id": RELEASE, "enabled": added, "already_published": skipped,
        "excluded_evaluation": evaluation, "integrity": integrity, "actor": actor,
        "expert_reviewed": False, "field_tested": False,
        "completed_at": datetime.now(UTC).isoformat(), "counts": store.library_counts()}
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--confirm-enable-all-reference", action="store_true")
    args = parser.parse_args()
    enable(args.db, args.output, args.actor, confirmed=args.confirm_enable_all_reference)


if __name__ == "__main__":
    main()
