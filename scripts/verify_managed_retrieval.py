"""离线链路冒烟：不调用云模型，不代表实拍准确性验证。"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import replace
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image

from camera_assistant.config import Settings
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.models import UserRequest
from camera_assistant.pipeline import CameraAssistantPipeline


def verify(database: Path, *, require_managed_env=False):
    settings = Settings.from_env()
    if require_managed_env and (settings.knowledge_mode != "managed"
                               or settings.knowledge_db_path.resolve() != database.resolve()):
        raise ValueError("running_environment_not_managed")
    settings = replace(settings, demo_mode=True, api_key="", knowledge_mode="managed",
                       knowledge_db_path=database, composition_enabled=True, detector_enabled=False)
    buffer = BytesIO()
    Image.new("RGB", (160, 120), (80, 90, 100)).save(buffer, format="JPEG")
    checks = {}
    start = time.monotonic()
    for device in ("camera", "phone"):
        result = CameraAssistantPipeline(settings).run(buffer.getvalue(), UserRequest(
            intent="室内人像 构图 主体 三分法 背景 留白 曝光 白平衡", device_type=device))
        if result.knowledge_mode != "managed" or not result.knowledge_hits or not result.composition_knowledge_hits:
            raise ValueError(f"retrieval_route_empty:{device}")
        hits = result.knowledge_hits + result.composition_knowledge_hits
        if any(hit.metadata.get("review_status") != "published" for hit in hits):
            raise ValueError("nonpublished_hit")
        checks[device] = {"parameter_ids": [h.document_id for h in result.knowledge_hits],
                         "composition_ids": [h.document_id for h in result.composition_knowledge_hits]}
    store = KnowledgeStore(database)
    retriever = ManagedKnowledgeRetriever(store)
    with sqlite3.connect(database) as connection:
        raw = connection.execute("SELECT record_json FROM revisions WHERE status='published' "
            "AND knowledge_id LIKE 'open-eq-v1-cameradatabase-%' LIMIT 1").fetchone()
    if raw:
        record = json.loads(raw[0])
        equipment = retriever.search(record["title"], libraries=["equipment"], conditions=record["conditions"])
        if not any(h.metadata["knowledge_id"] == record["knowledge_id"] for h in equipment):
            raise ValueError("exact_equipment_not_found")
        checks["equipment"] = record["knowledge_id"]
    result = {"mode": "managed", "offline_demo_only": True, "cloud_calls": 0,
              "elapsed_seconds": round(time.monotonic()-start, 2), "checks": checks}
    print(json.dumps(result, ensure_ascii=True), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--require-managed-env", action="store_true")
    args = parser.parse_args()
    verify(args.db, require_managed_env=args.require_managed_env)
