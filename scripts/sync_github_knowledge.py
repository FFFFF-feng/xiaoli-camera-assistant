"""只读 GitHub 知识文本，预览去重；--apply 才同步文件并备份导入本地草稿。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from camera_assistant.knowledge.importer import parse_record_file
from camera_assistant.knowledge.models import KnowledgeRecord
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeStore

REPOSITORY = "FFFFF-feng/xiaoli-camera-assistant"
PREFIX = "data/knowledge_drafts/"
COLLECTIONS = ("mobile-models-20261014", "photography-20261013", "starter-v1")
MAX_BYTES = 2 * 1024 * 1024


def canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_hash(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data, usedforsecurity=False).hexdigest()


def write_new(path: Path, data: bytes) -> None:
    if not path.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("拒绝写入工作区以外的路径或目录链接")
    if path.exists():
        if path.is_symlink() or path.read_bytes() != data:
            raise ValueError(f"拒绝覆盖已有不同内容或链接：{path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)


def write_json(path: Path, value: object) -> None:
    write_new(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"),
    )


def gh_json(endpoint: str) -> dict:
    executable = shutil.which("gh")
    if not executable:
        raise ValueError("需要已登录的 GitHub CLI；请先执行 gh auth login")
    result = subprocess.run(
        [executable, "api", endpoint], capture_output=True, check=False, timeout=60
    )
    if result.returncode:
        raise ValueError("GitHub API 读取失败，请检查网络及登录；未打印凭据或错误响应正文")
    return json.loads(result.stdout)


def safe_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or ".." in path.parts
        or any(":" in part for part in path.parts)
        or path.as_posix() != value
    ):
        raise ValueError("仓库路径不安全")
    if len(path.parts) < 4 or path.parts[:2] != ("data", "knowledge_drafts"):
        raise ValueError("文件不属于知识草稿目录")
    if path.parts[2] not in COLLECTIONS:
        raise ValueError("资料集不在本轮同步范围")
    return path


def is_card(path: str) -> bool:
    parts = safe_path(path).parts
    return "upload_cards" in parts[3:] or (
        parts[2] == "starter-v1" and len(parts) == 4 and parts[-1] != "README.md"
    )


def snapshot(commit: str, offline: bool) -> tuple[Path, list[dict]]:
    cache = ROOT / "data/source_cache" / f"github-knowledge-{commit}"
    tree_path = cache / "tree.json"
    if offline:
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
    else:
        tree = gh_json(f"repos/{REPOSITORY}/git/trees/{commit}?recursive=1")
        write_json(tree_path, tree)
    if tree.get("sha") != commit or tree.get("truncated"):
        raise ValueError("仓库文件树不完整或提交不符")
    files = []
    for item in tree["tree"]:
        path = item["path"]
        if item["type"] != "blob" or not any(
            path.startswith(f"{PREFIX}{collection}/") for collection in COLLECTIONS
        ):
            continue
        safe_path(path)
        if PurePosixPath(path).suffix not in {".json", ".yaml", ".yml", ".md"}:
            continue  # 不下载或执行 Python、二进制、媒体和其他代码。
        if item.get("mode") != "100644" or item.get("size", MAX_BYTES + 1) > MAX_BYTES:
            raise ValueError("不下载链接、可执行文件或超限文本")
        files.append(item)
    if not files:
        raise ValueError("指定版本没有知识文本")

    def fetch(item: dict) -> dict:
        path = item["path"]
        destination = cache / path
        if destination.exists():
            data = destination.read_bytes()
        elif offline:
            raise ValueError(f"缺少离线快照：{path}")
        else:
            local = ROOT / path
            existing = local.read_bytes() if local.is_file() and not local.is_symlink() else b""
            if git_hash(existing) == item["sha"]:
                data = existing
            else:
                url = f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{quote(path)}"
                request = Request(url, headers={"User-Agent": "XiaoliKnowledgeSync/1.0"})
                with urlopen(request, timeout=40) as response:
                    if response.url != url:
                        raise ValueError("下载发生重定向，停止同步")
                    data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES or git_hash(data) != item["sha"]:
                raise ValueError(f"来源 Git blob 校验失败：{path}")
            data.decode("utf-8-sig")
            write_new(destination, data)
        if len(data) > MAX_BYTES or git_hash(data) != item["sha"]:
            raise ValueError(f"来源快照不完整或被修改：{path}")
        return {
            "path": path,
            "git_blob_sha": item["sha"],
            "sha256": sha256(data),
            "bytes": len(data),
            "is_card": is_card(path),
        }

    with ThreadPoolExecutor(max_workers=6) as executor:
        metadata = list(executor.map(fetch, sorted(files, key=lambda item: item["path"])))
    return cache, metadata


def load_cards(cache: Path, files: list[dict]) -> tuple[list[tuple[str, KnowledgeRecord]], list]:
    cards = [
        (item["path"], parse_record_file(cache / item["path"])) for item in files if item["is_card"]
    ]
    validated_manifests = []
    for collection in COLLECTIONS:
        root = f"{PREFIX}{collection}"
        manifest_path = cache / root / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        listed = manifest["cards"]
        paths = set()
        for item in listed:
            relative = item.get("file", item.get("path"))
            path = f"{root}/{relative}"
            safe_path(path)
            if path in paths or not is_card(path):
                raise ValueError("集合清单有重复或非知识卡路径")
            paths.add(path)
            data = (cache / path).read_bytes()
            if sha256(data) != item["sha256"]:
                raise ValueError("卡片与团队清单 SHA256 不符")
            record = parse_record_file(cache / path)
            for key in ("knowledge_id", "version", "library_id", "author"):
                if getattr(record, key) != item[key]:
                    raise ValueError("卡片身份或署名与清单不符")
        expected = manifest.get("count", manifest.get("card_count"))
        actual = {path for path, _ in cards if path.startswith(root + "/")}
        if expected != len(listed) or paths != actual:
            raise ValueError("集合清单与实际知识文件数量不符")
        validated_manifests.append(
            {"collection": collection, "cards": len(listed), "sha256_verified": True}
        )
    return cards, validated_manifests


def read_rows(database: Path) -> dict[tuple[str, int], tuple]:
    if not database.exists():
        return {}
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        if conn.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("本地知识库版本不受支持")
        return {(row[0], row[1]): row for row in conn.execute("SELECT * FROM revisions")}


def strict_fingerprint(record: KnowledgeRecord) -> str:
    # 仅排除逻辑 ID 和版本；正文、适用条件、全部证据、许可、作者必须仍完全相同。
    data = record.model_dump(mode="json", exclude={"knowledge_id", "version"})
    return sha256(canonical(data).encode("utf-8"))


def normalized_title(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKC", value).casefold() if char.isalnum()
    )


def plan_merge(
    incoming: list[tuple[str, KnowledgeRecord]], rows: dict, local_conflicts: set[str] | None = None
) -> tuple[list[KnowledgeRecord], dict]:
    existing = {key: KnowledgeRecord.model_validate_json(row[3]) for key, row in rows.items()}
    latest = defaultdict(int)
    fingerprints = {}
    titles = defaultdict(list)
    for (knowledge_id, version), record in existing.items():
        latest[knowledge_id] = max(latest[knowledge_id], version)
        fingerprints[strict_fingerprint(record)] = knowledge_id
        titles[(record.library_id, normalized_title(record.title))].append(knowledge_id)
    skipped = []
    conflicts = []
    related = []
    candidates = {}
    blocked = set()
    for path, record in incoming:
        key = (record.knowledge_id, record.version)
        if path in (local_conflicts or set()):
            conflicts.append(
                {"path": path, "knowledge_id": key[0], "reason": "local_file_differs_from_remote"}
            )
            blocked.add(key[0])
            continue
        previous = candidates.get(key)
        if previous:
            if canonical(previous.model_dump(mode="json")) == canonical(
                record.model_dump(mode="json")
            ):
                skipped.append(
                    {"path": path, "knowledge_id": key[0], "reason": "duplicate_incoming"}
                )
            else:
                conflicts.append(
                    {
                        "path": path,
                        "knowledge_id": key[0],
                        "reason": "same_id_version_different_incoming_content",
                    }
                )
                blocked.add(key[0])
            continue
        candidates[key] = record
    selected = []
    for key, record in sorted(candidates.items()):
        knowledge_id, version = key
        if knowledge_id in blocked:
            continue
        old = existing.get(key)
        if old:
            if canonical(old.model_dump(mode="json")) == canonical(record.model_dump(mode="json")):
                skipped.append(
                    {
                        "knowledge_id": knowledge_id,
                        "version": version,
                        "reason": "same_id_version_identical",
                    }
                )
            else:
                conflicts.append(
                    {
                        "knowledge_id": knowledge_id,
                        "version": version,
                        "reason": "same_id_version_different_database_content",
                    }
                )
            continue
        versions = [item for (identity, _), item in existing.items() if identity == knowledge_id]
        if any(item.library_id != record.library_id for item in versions):
            conflicts.append({"knowledge_id": knowledge_id, "reason": "library_changed"})
            continue
        if version <= latest[knowledge_id]:
            skipped.append(
                {
                    "knowledge_id": knowledge_id,
                    "version": version,
                    "reason": "older_than_database_latest_version",
                }
            )
            continue
        fingerprint = strict_fingerprint(record)
        if fingerprint in fingerprints:
            skipped.append(
                {
                    "knowledge_id": knowledge_id,
                    "version": version,
                    "reason": "identical_record_different_id",
                    "retained_knowledge_id": fingerprints[fingerprint],
                }
            )
            continue
        same_title = titles.get((record.library_id, normalized_title(record.title)), [])
        if same_title:
            related.append(
                {
                    "knowledge_id": knowledge_id,
                    "possible_related_ids": same_title[:20],
                    "reason": "same_title_not_enough_to_merge",
                    "automatically_merged": False,
                }
            )
        fingerprints[fingerprint] = knowledge_id
        titles[(record.library_id, normalized_title(record.title))].append(knowledge_id)
        selected.append(record)
    summary = {
        "incoming_cards": len(incoming),
        "selected_for_import": len(selected),
        "skipped_count": len(skipped),
        "conflict_count": len(conflicts),
        "selected_by_library": dict(Counter(item.library_id for item in selected)),
        "selected_by_id_prefix": dict(
            Counter(item.knowledge_id.split("-")[0] for item in selected)
        ),
        "skipped": skipped,
        "conflicts": conflicts,
        "related_titles": related,
    }
    return selected, summary


def synchronize_files(cache: Path, files: list[dict], apply: bool) -> tuple[set[str], dict]:
    conflicts = set()
    counts = Counter()
    for item in files:
        source = cache / item["path"]
        target = ROOT / item["path"]
        data = source.read_bytes()
        if target.exists():
            if target.is_symlink():
                conflicts.add(item["path"])
                counts["local_symlink_not_touched"] += 1
            elif target.read_bytes() == data:
                counts["already_identical"] += 1
            else:
                # 只容忍 Git 的换行转换；不覆写任何本地内容。
                if target.read_bytes().replace(b"\r\n", b"\n") == data.replace(b"\r\n", b"\n"):
                    counts["line_endings_only_preserved"] += 1
                else:
                    conflicts.add(item["path"])
                    counts["local_changes_preserved"] += 1
        else:
            counts["new_files_synced" if apply else "new_files_pending"] += 1
            if apply:
                write_new(target, data)
    return conflicts, dict(counts)


def apply_merge(
    database: Path, selected: list[KnowledgeRecord], before: dict, report_directory: Path
) -> dict:
    # 验证真实公共写入接口、重复写入和草稿的检索隔离，绝不执行上游验证脚本。
    with tempfile.TemporaryDirectory(prefix="xiaoli-github-sync-") as temporary:
        store = KnowledgeStore(Path(temporary) / "validation.db")
        store.save_many_drafts(selected)
        audit_count = len(store.audit_log())
        store.save_many_drafts(selected)
        if len(store.audit_log()) != audit_count or len(store.list_revisions()) != len(selected):
            raise ValueError("独立测试库重复导入检查失败")
        if ManagedKnowledgeRetriever(store).search("手机 相机 摄影"):
            raise ValueError("草稿进入了正式检索")
    # 预览期间数据库变化则停止，不根据过期的去重计划写入。
    if read_rows(database) != before:
        raise ValueError("数据库在计划后发生变化，请重新预览")
    backup = None
    if database.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = ROOT / "data/backups" / f"before-github-sync-{stamp}.db"
        backup.parent.mkdir(parents=True, exist_ok=True)
        with (
            closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn,
            closing(sqlite3.connect(backup)) as destination,
        ):
            conn.backup(destination)
    store = KnowledgeStore(database)
    imported = store.save_many_drafts(selected)
    after = read_rows(database)
    preserved = all(after.get(key) == row for key, row in before.items())
    keys = {(record.knowledge_id, record.version) for record in selected}
    added = set(after) - set(before)
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if (
        not preserved
        or added != keys
        or integrity != "ok"
        or any(after[key][4] != "draft" for key in keys)
    ):
        raise ValueError("导入后保留性检查异常；备份已保留，不自动覆盖并行写入")
    # 在真实目标库再重复一次公共写入；已有草稿/审核状态和审计均不得改变。
    audits = len(store.audit_log())
    store.save_many_drafts(selected)
    if read_rows(database) != after or len(store.audit_log()) != audits:
        raise ValueError("本地库重复导入不满足幂等性")
    result = {
        "database": str(database.resolve()),
        "backup": str(backup) if backup else None,
        "records_before": len(before),
        "records_after": len(after),
        "imported_count": len(imported),
        "old_rows_preserved": preserved,
        "new_rows_all_draft": True,
        "sqlite_integrity": integrity,
        "real_database_repeat_import_new_rows": 0,
        "new_retrieval_allowed_count": sum(
            item.record.source.retrieval_allowed for item in imported
        ),
    }
    write_json(report_directory / "database-import.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", help="固定 40 位 Git 提交；默认读取远端 main 最新提交")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--db", type=Path, default=ROOT / "data/knowledge.db")
    parser.add_argument("--apply", action="store_true", help="同步缺失知识文本并备份导入草稿")
    args = parser.parse_args()
    if args.offline and not args.commit:
        parser.error("离线模式需要指定 --commit")
    commit = args.commit or gh_json(f"repos/{REPOSITORY}/commits/main")["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("需要完整的 Git 提交 SHA")
    cache, files = snapshot(commit, args.offline)
    incoming, manifests = load_cards(cache, files)
    file_conflicts, sync_result = synchronize_files(cache, files, args.apply)
    before = read_rows(args.db)
    selected, plan = plan_merge(incoming, before, file_conflicts)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    report_directory = ROOT / "knowledge_sources" / f"github-sync-{commit[:12]}" / stamp
    report = {
        "repository": f"https://github.com/{REPOSITORY}",
        "commit": commit,
        "collections": COLLECTIONS,
        "apply": args.apply,
        "files": files,
        "manifest_checks": manifests,
        "file_sync": sync_result,
        "local_file_conflicts": sorted(file_conflicts),
        "merge_plan": plan,
        "notes": [
            "只做严格记录去重，不宣称已完成语义合并或厂家事实核验。",
            "不修改作者、正文、来源、许可和版本；不审核发布，不改运行时设备目录。",
        ],
    }
    if args.apply:
        report["database_import"] = apply_merge(args.db, selected, before, report_directory)
    write_json(report_directory / "sync-report.json", report)
    summary = {key: value for key, value in report.items() if key not in {"files", "merge_plan"}}
    summary["merge_plan"] = {
        key: value
        for key, value in plan.items()
        if key not in {"skipped", "conflicts", "related_titles"}
    }
    summary["report"] = str(report_directory / "sync-report.json")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
