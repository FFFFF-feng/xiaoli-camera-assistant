"""固定开源版本的设备资料转换；只生成待审核知识卡，不发布或修改设备选项。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

BATCH = "opensource-equipment-20261014"
CACHE = ROOT / "data/source_cache" / BATCH
REPORTS = ROOT / "knowledge_sources" / BATCH
CARDS = ROOT / "data/knowledge_drafts" / BATCH
MAX_SOURCE_BYTES = 32 * 1024 * 1024
SOURCES = {
    "cameradatabase": {
        "repo": "leavestylecode/CameraDatabase",
        "commit": "374a630bac7847f851b3746e82aa528262ef0b5c",
        "license": "MIT",
        "credit": "CameraDatabase, leavestylecode and contributors",
        "files": ["data/camera_data.json", "LICENSE", "README.md"],
    },
    "opensfm": {
        "repo": "mapillary/OpenSfM",
        "commit": "b25c07b648b49352797125f2b40f9cef28bbac62",
        "license": "BSD-2-Clause",
        "credit": "OpenSfM, Mapillary and contributors",
        "files": [
            "opensfm/data/sensor_data.json",
            "opensfm/data/sensor_data.readme.txt",
            "LICENSE",
        ],
    },
    "zmount": {
        "repo": "KatsuraIwamoto/z-mount-product-database",
        "commit": "4a792e661ad85b1527a5447503c0b0ceaf5c4923",
        "license": "CC-BY-4.0",
        "credit": "Z Mount Product Database, Katsura Iwamoto",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "files": [
            "dist/z-mount-lenses.full.json",
            "dist/z-mount-adapters.full.json",
            "LICENSING.md",
            "LICENSES/CC-BY-4.0.txt",
            "data/LICENSE",
        ],
    },
    "lensfun": {
        "repo": "lensfun/lensfun",
        "commit": "43f9e001ab66c4fcdd4f400463f13b72f94b2288",
        "license": "CC-BY-SA-3.0",
        "credit": "Lensfun database, Lensfun contributors; see retained XML notices",
        "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
        "files": ["data/COPYING.CC_BY-SA_3.0", "README.md"],
    },
}


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_once(path: Path, data: bytes) -> None:
    """已有不同内容即停止，不覆盖队友或人工编辑的数据。"""
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"已有文件内容不同，拒绝覆盖：{path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)


def download(url: str, path: Path) -> bytes:
    if path.exists():
        data = path.read_bytes()
    else:
        request = Request(url, headers={"User-Agent": "XiaoliCameraAssistant-source-review/1.0"})
        with urlopen(request, timeout=40) as response:
            if response.url != url:
                raise ValueError("来源发生重定向，请人工检查")
            data = response.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES:
            raise ValueError("来源超过大小限制")
        data.decode("utf-8")
        save_once(path, data)
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError("缓存超过大小限制")
    return data


def source_path(source: str, path: str) -> Path:
    return CACHE / source / path


def source_url(source: str, path: str) -> str:
    spec = SOURCES[source]
    return f"https://raw.githubusercontent.com/{spec['repo']}/{spec['commit']}/{path}"


@lru_cache(maxsize=128)
def source_hash(source: str, path: str) -> str:
    return sha256(source_path(source, path).read_bytes())


def fetch_sources() -> list[dict]:
    spec = SOURCES["lensfun"]
    tree_url = f"https://api.github.com/repos/{spec['repo']}/git/trees/{spec['commit']}?recursive=1"
    tree = json.loads(download(tree_url, CACHE / "lensfun/tree.json"))
    if tree.get("truncated") or tree.get("sha") != spec["commit"]:
        raise ValueError("Lensfun 文件树不完整或版本不符")
    xml_paths = sorted(
        item["path"]
        for item in tree["tree"]
        if item["type"] == "blob" and re.fullmatch(r"data/db/[\w-]+\.xml", item["path"])
    )
    jobs = [
        (name, path)
        for name, config in SOURCES.items()
        for path in list(config["files"]) + (xml_paths if name == "lensfun" else [])
    ]

    def fetch(job: tuple[str, str]) -> dict:
        name, path = job
        url = source_url(name, path)
        data = download(url, source_path(name, path))
        return {
            "source": name,
            "path": path,
            "url": url,
            "bytes": len(data),
            "sha256": sha256(data),
        }

    with ThreadPoolExecutor(max_workers=6) as executor:
        files = list(executor.map(fetch, jobs))
    save_once(REPORTS / "source-manifest.json", encoded({"sources": SOURCES, "files": files}))
    # 许可文件与数据快照分开保留，随转换后的资料一并交付。
    for item in files:
        path = item["path"]
        if (
            "LICENSE" in path
            or "LICENSING" in path
            or "COPYING" in path
            or path.endswith("readme.txt")
        ):
            save_once(
                REPORTS / "licenses" / item["source"] / Path(path).name,
                source_path(item["source"], path).read_bytes(),
            )
    return files


def normalized(value: str) -> str:
    """只统一 Unicode、大小写和空白，不模糊合并型号或地区别名。"""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def full_model(brand: str, model: str) -> str:
    if normalized(model).startswith(normalized(brand) + " "):
        return model.strip()
    return f"{brand.strip()} {model.strip()}"


def sensor_dimensions(text: object) -> tuple[float, float] | None:
    # 只解析已给出的毫米尺寸；绝不把 1/2.3 英寸型传感器换算为英寸长度。
    match = re.search(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*mm", str(text))
    if match:
        width, height = map(float, match.groups())
        if 0 < height <= width <= 100:
            return width, height
    return None


def consistency_check(model: str, sensor: object, widths: dict[str, list]) -> dict:
    dimensions = sensor_dimensions(sensor)
    candidates = widths.get(normalized(model), [])
    check = {
        "field": "sensor_width_mm",
        "status": "not_comparable",
        "independent_evidence": False,
        "limitation": "OpenSfM 初始数据来自 Digicamdb；同源风险，不代表独立或厂家核验。",
    }
    if dimensions:
        check["cameradatabase_width_mm"] = dimensions[0]
    if not candidates or not dimensions:
        return check
    if len(candidates) != 1:
        return {**check, "status": "ambiguous_model", "candidates": candidates}
    name, width = candidates[0]
    check.update(opensfm_model=name, opensfm_width_mm=width)
    if isinstance(width, bool) or not isinstance(width, (int, float)) or not 0 < width <= 100:
        return {**check, "status": "invalid_reference_width"}
    tolerance = max(0.1, dimensions[0] * 0.01)
    delta = abs(dimensions[0] - width)
    return {
        **check,
        "status": "consistent" if delta <= tolerance else "conflict",
        "absolute_difference_mm": round(delta, 6),
        "tolerance_mm": round(tolerance, 6),
        "matching": "NFKC + casefold + whitespace only; full brand/model exact match",
    }


def provenance(source: str, path: str, locator: str) -> dict:
    config = SOURCES[source]
    return {
        "repository": f"https://github.com/{config['repo']}",
        "commit": config["commit"],
        "path": path,
        "record_locator": locator,
        "file_sha256": source_hash(source, path),
        "license": config["license"],
        "attribution": config["credit"],
        "license_url": config.get("license_url", ""),
        "changes": "提取设备文本字段，转换为项目 JSON 知识卡，补充中文使用边界；未下载媒体。",
    }


def make_card(
    source: str,
    path: str,
    locator: str,
    model: str,
    entity: str,
    payload: dict,
    content: str,
    conditions: dict,
) -> dict:
    from camera_assistant.knowledge.models import KnowledgeRecord

    identity = f"{source}\0{path}\0{locator}\0{model}"
    slug = re.sub(r"[^a-z0-9]+", "-", normalized(model)).strip("-")[:48] or "device"
    knowledge_id = f"open-eq-v1-{source}-{slug}-{sha256(identity.encode('utf-8'))[:16]}"
    config = SOURCES[source]
    labels = {
        "camera": "相机",
        "lens": "镜头",
        "adapter": "转接器",
        "teleconverter": "增距镜",
        "pinhole": "针孔光学产品",
    }
    record = KnowledgeRecord.model_validate(
        {
            "knowledge_id": knowledge_id,
            "library_id": "equipment",
            "title": f"[待核验设备档案] {model} {labels[entity]}",
            "kind": "guideline",
            "content": content,
            "payload": {
                "device_type": "camera",
                "entity_type": entity,
                "model": model,
                "provenance": provenance(source, path, locator),
                "verification": {"level": "upstream_dataset_only", "officially_verified": False},
                "usage": {
                    "role": "equipment_reference_draft",
                    "controls_hardware_limits": False,
                    "manual_review_required": True,
                    "limitations": [
                        "不能直接覆盖运行时设备档案或生成曝光参数。",
                        "空值是未知，不等于不支持；型号、地区版本和固件须核对。",
                    ],
                },
                **payload,
            },
            "tags": ["开源设备目录", "待核验", labels[entity], source],
            "conditions": {"device_type": "camera", **conditions},
            "source": {
                "name": config["credit"],
                "url": f"https://github.com/{config['repo']}/blob/{config['commit']}/{path}",
                "location": locator,
                "license": config["license"],
                "retrieval_allowed": False,
            },
            "author": "小栗项目设备资料转换",
            "version": 1,
            "schema_version": 1,
            "dataset_split": "reference",
        }
    )
    return record.model_dump(mode="json")


def camera_cards() -> list[dict]:
    path = "data/camera_data.json"
    cameras = json.loads(source_path("cameradatabase", path).read_text(encoding="utf-8"))
    sensor_path = "opensfm/data/sensor_data.json"
    sensors = json.loads(source_path("opensfm", sensor_path).read_text(encoding="utf-8"))
    widths = defaultdict(list)
    for model, width in sensors.items():
        widths[normalized(model)].append([model, width])
    cards = []
    identities = set()
    for index, item in enumerate(cameras):
        brand, name = item["Brand"], item["Model"]
        if (
            not isinstance(brand, str)
            or not brand.strip()
            or not isinstance(name, str)
            or not name.strip()
        ):
            raise ValueError("相机记录缺少品牌或型号")
        model = full_model(brand, name)
        identity = (brand, name)
        if identity in identities:
            raise ValueError("相机来源有重复型号，需人工处理")
        identities.add(identity)
        check = consistency_check(model, item.get("Sensor size"), widths)
        specs = {key: value for key, value in item.items() if key != "image_file"}
        content = (
            f"设备：{model}。开源目录记载的传感器尺寸：{item.get('Sensor size') or '未知'}；"
            f"传感器类型：{item.get('Sensor type') or '未知'}；上市年份：{item.get('Year') or '未知'}。\n"
            "适用规则：仅与完整品牌及型号相同的设备比对；保留原始规格，不推断原生卡口或套机镜头。\n"
            "ISO 文本可能包含扩展感光度；未分机械与电子的快门字段不能作为机械快门上限。"
            "光圈、等效光圈、35mm 等效焦距不得混用；空白字段保持未知。\n"
            f"传感器宽度跨库检查：{check['status']}；并非独立厂家证据。"
        )
        cards.append(
            make_card(
                "cameradatabase",
                path,
                f"array[{index}]",
                model,
                "camera",
                {
                    "brand": brand,
                    "source_specs": specs,
                    "consistency_checks": [check],
                    "cross_reference": provenance("opensfm", sensor_path, model),
                },
                content,
                {"camera_model": model},
            )
        )
    return cards


def xml_values(node: ET.Element, tag: str) -> list[dict]:
    return [
        {"text": child.text.strip() if child.text else "", "attributes": dict(child.attrib)}
        for child in node.findall(tag)
    ]


def lensfun_cards() -> list[dict]:
    cards = []
    for filename in sorted((CACHE / "lensfun/data/db").glob("*.xml")):
        data = filename.read_bytes()
        # ElementTree 不加载外部 DTD；同时拒绝实体声明，保持外部数据不执行。
        if b"<!ENTITY" in data.upper():
            raise ValueError("Lensfun XML 含实体声明")
        root = ET.fromstring(data)
        path = f"data/db/{filename.name}"
        save_once(REPORTS / "lensfun-original" / filename.name, data)
        for entity in ("camera", "lens"):
            for index, node in enumerate(root.findall(entity)):
                brand, name = node.findtext("maker", "").strip(), node.findtext("model", "").strip()
                if not brand or not name:
                    raise ValueError("Lensfun 缺少品牌或型号")
                model = full_model(brand, name)
                aliases = list(
                    dict.fromkeys(
                        [model]
                        + [full_model(brand, value["text"]) for value in xml_values(node, "model")]
                    )
                )
                mounts = [item["text"] for item in xml_values(node, "mount")]
                metadata = {
                    tag: xml_values(node, tag)
                    for tag in (
                        "maker",
                        "model",
                        "mount",
                        "cropfactor",
                        "aspect-ratio",
                        "focal",
                        "aperture",
                        "type",
                    )
                    if node.findall(tag)
                }
                calibration_counts = Counter(
                    child.tag
                    for calibration in node.findall("calibration")
                    for child in calibration
                )
                content = (
                    f"设备：{model}。Lensfun 记录的卡口：{'、'.join(mounts) or '未知'}；"
                    f"原始裁切系数：{node.findtext('cropfactor', '未知')}。\n"
                    "适用规则：完整型号和具体卡口版本一致才可使用；同名多卡口镜头不能直接互换。\n"
                    "Lensfun 的 mount compat 不是原生兼容保证，不据此推荐无需转接环。"
                    "校正用 cropfactor 不直接视作厂家标称画幅；不从畸变或暗角校正采样点"
                    "推断完整焦段、最大光圈、自动对焦或防抖能力。"
                )
                condition = {"camera_model" if entity == "camera" else "lens_model": aliases}
                cards.append(
                    make_card(
                        "lensfun",
                        path,
                        f"{entity}[{index}]",
                        model,
                        entity,
                        {
                            "brand": brand,
                            "aliases": aliases,
                            "mounts": mounts,
                            "source_metadata": metadata,
                            "calibration_sample_counts": dict(calibration_counts),
                            "derived_data_license": "CC-BY-SA-3.0",
                        },
                        content,
                        condition,
                    )
                )
    return cards


def zmount_cards() -> list[dict]:
    cards = []
    for category, key in (("lenses", "products"), ("adapters", "adapters")):
        path = f"dist/z-mount-{category}.full.json"
        dataset = json.loads(source_path("zmount", path).read_text(encoding="utf-8"))
        products = dataset[key]
        if dataset["license"] != "CC-BY-4.0" or len(products) != dataset["recordCount"]:
            raise ValueError("Z Mount 数据许可或数量不符")
        if len({item["id"] for item in products}) != len(products):
            raise ValueError("Z Mount 产品 ID 重复")
        for product in products:
            model = product["identity"]["productName"]
            entity = product.get("productType", "adapter")
            if entity not in {"lens", "adapter", "teleconverter", "pinhole"}:
                raise ValueError("未处理的 Z Mount 产品类型")
            brand_id = product["identity"].get("brandId")
            brand = dataset["referenceData"]["brands"].get(brand_id, {}).get("name", brand_id)
            refs = dataset["referenceData"]["mountSystems"]
            if entity == "adapter":
                mount_notes = []
                for item in product.get("mountConfigurations", []):
                    left, right = (
                        item.get("lensSideMountSystemId"),
                        item.get("cameraSideMountSystemId"),
                    )
                    mount_notes.append(f"镜头侧 {left} → 机身侧 {right}")
                condition = {"camera_mount": "nikon_z"}
                scope = "；".join(mount_notes) or "转接方向未知"
            else:
                mount_id = product.get("mount", {}).get("systemId")
                scope = refs.get(mount_id, {}).get("name", mount_id) or "未知"
                condition = {"lens_model": model}
            content = (
                f"设备：{model}。产品类型：{entity}；来源记录卡口或方向：{scope}。\n"
                "适用规则：必须匹配完整型号、卡口、画幅与使用条件；保留原始结构中的焦距、"
                "光圈条件及未知值，不将增距镜或针孔产品当作普通摄影镜头。\n"
                "转接器电子触点、自动对焦等上游声明不是任意机身镜头组合的实测保证，"
                "还需核对两侧设备及固件。官方页面链接仅供复核，未据链接自动标为厂家已验证。"
            )
            cards.append(
                make_card(
                    "zmount",
                    path,
                    f"{key}[id={product['id']}]",
                    model,
                    entity,
                    {
                        "brand": brand,
                        "source_product_id": product["id"],
                        "source_product": product,
                        "data_version": dataset["dataVersion"],
                        "source_dataset_content_hash": dataset["contentHash"],
                        "mount_system_dictionary": refs,
                        "release_blockers": ["转接器组合级精确匹配尚未实现，禁止批量发布。"]
                        if entity == "adapter"
                        else ["核对厂家规格与运行时设备型号别名。"],
                    },
                    content,
                    condition,
                )
            )
    return cards


def prepare_cards() -> tuple[dict, list[dict]]:
    cards = camera_cards() + lensfun_cards() + zmount_cards()
    cards.sort(key=lambda item: item["knowledge_id"])
    if len({item["knowledge_id"] for item in cards}) != len(cards):
        raise ValueError("生成的知识 ID 冲突")
    counts = Counter()
    groups = Counter()
    index = []
    selected = []
    for card in cards:
        source = card["tags"][-1]
        entity = card["payload"]["entity_type"]
        group = f"{source}-{entity}"
        part = groups[group] // 20 + 1
        groups[group] += 1
        relative = Path(group) / f"part-{part:03d}" / f"{card['knowledge_id']}.json"
        data = encoded(card)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("生成的卡片超过单文件上传限制")
        save_once(CARDS / relative, data)
        counts[group] += 1
        index.append(
            {
                "knowledge_id": card["knowledge_id"],
                "model": card["payload"]["model"],
                "entity_type": entity,
                "source": source,
                "file": relative.as_posix(),
                "sha256": sha256(data),
            }
        )
        # 单独示例目录不参与整批 CLI 导入；方便在 UI 验证真实型号、镜头、转接器。
        if (
            (
                source == "cameradatabase"
                and any(
                    term in normalized(card["payload"]["model"])
                    for term in ("canon eos r50", "nikon z6", "fujifilm x-t5", "sony a7 iv")
                )
            )
            or (source == "lensfun" and "18-55" in card["payload"]["model"])
            or (source == "zmount" and entity == "adapter")
        ):
            selected.append(card)
    # 保证 UI 样本兼有相机、镜头、转接器，而非被单一类别占满。
    demo = []
    for source, entity, limit in (
        ("cameradatabase", "camera", 6),
        ("lensfun", "lens", 10),
        ("zmount", "adapter", 4),
    ):
        demo.extend(
            [
                card
                for card in selected
                if card["tags"][-1] == source and card["payload"]["entity_type"] == entity
            ][:limit]
        )
    demo_dir = ROOT / "data/knowledge_samples" / BATCH
    for number, card in enumerate(demo, 1):
        save_once(demo_dir / f"{number:02d}-{card['knowledge_id']}.json", encoded(card))
    check_counts = Counter(
        check["status"] for card in cards for check in card["payload"].get("consistency_checks", [])
    )
    conflicts = [
        {
            "knowledge_id": card["knowledge_id"],
            "model": card["payload"]["model"],
            "check": card["payload"]["consistency_checks"][0],
        }
        for card in cards
        if card["payload"].get("consistency_checks", [{}])[0].get("status") == "conflict"
    ]
    report = {
        "batch": BATCH,
        "total_cards": len(cards),
        "by_source_and_entity": dict(counts),
        "card_counts_are_not_unique_device_counts": True,
        "sensor_width_consistency": dict(check_counts),
        "sensor_width_conflicts": conflicts,
        "sensor_width_tolerance": "max(0.1 mm, CameraDatabase width * 1%)",
        "sensor_sources_independent": False,
        "officially_verified_cards": 0,
        "retrieval_allowed_cards": 0,
        "phone_cards": 0,
        "ui_sample_cards": len(demo),
        "review_note": "所有记录仅核验上游结构与可追溯性；并非全量厂家规格核验。",
        "index": index,
    }
    save_once(REPORTS / "conversion-report.json", encoded(report))
    return report, cards


def import_drafts(db: Path, cards: list[dict]) -> dict:
    """仅经显式 --import-db 执行；先备份、验证旧行和发布状态，不覆盖旧记录。"""
    from camera_assistant.knowledge.models import KnowledgeRecord
    from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
    from camera_assistant.knowledge.store import KnowledgeStore

    records = [KnowledgeRecord.model_validate(card) for card in cards]
    if not records or len({(item.knowledge_id, item.version) for item in records}) != len(records):
        raise ValueError("没有设备卡或同批知识 ID 重复")
    if any(item.library_id != "equipment" or item.source.retrieval_allowed for item in records):
        raise ValueError("本脚本只导入不允许检索的器材草稿")
    # 先在独立临时库验证整批导入、幂等性和草稿检索隔离。
    with tempfile.TemporaryDirectory(prefix="xiaoli-equipment-check-") as temporary:
        store = KnowledgeStore(Path(temporary) / "validation.db")
        first = store.save_many_drafts(records)
        audits_before = len(store.audit_log())
        second = store.save_many_drafts(records)
        if not (
            len(first) == len(records) == len(second)
            and [item.content_hash for item in first] == [item.content_hash for item in second]
            and len(store.audit_log()) == audits_before
        ):
            raise ValueError("隔离导入或重复导入验证失败")
        if ManagedKnowledgeRetriever(store).search("Canon Nikon 18-55", libraries=["equipment"]):
            raise ValueError("未审核草稿进入检索")
    backup = None
    before = {}
    if db.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = ROOT / "data/backups" / f"before-{BATCH}-{stamp}.db"
        backup.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            with closing(sqlite3.connect(backup)) as dest:
                conn.backup(dest)
            before = {(row[0], row[1]): row for row in conn.execute("SELECT * FROM revisions")}
    # 与 CLI 和上传 UI 使用同一公共事务写入接口。卡片文件已由 save_once 与内存记录逐字节核对。
    revisions = KnowledgeStore(db).save_many_drafts(records)
    with closing(sqlite3.connect(db)) as conn:
        after = {(row[0], row[1]): row for row in conn.execute("SELECT * FROM revisions")}
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    preserved = all(after.get(identity) == row for identity, row in before.items())
    new_rows = [row for identity, row in after.items() if identity not in before]
    if (
        not preserved
        or integrity != "ok"
        or any(
            row[4] != "draft" or json.loads(row[3])["source"]["retrieval_allowed"]
            for row in new_rows
        )
    ):
        raise ValueError("导入后安全校验异常；保留备份，需人工检查，不自动回滚其他并行写入")
    audit = {
        "database": str(db.resolve()),
        "backup": str(backup) if backup else None,
        "records_before": len(before),
        "records_after": len(after),
        "old_rows_preserved": preserved,
        "sqlite_integrity": integrity,
        "new_rows_are_nonretrievable_drafts": True,
        "isolated_full_import_and_idempotence_passed": True,
        "import": {
            "success": True,
            "validated_count": len(records),
            "imported_count": sum(
                (item.record.knowledge_id, item.record.version) not in before for item in revisions
            ),
            "unchanged_count": sum(
                (item.record.knowledge_id, item.record.version) in before for item in revisions
            ),
            "revisions": [
                {
                    "knowledge_id": item.record.knowledge_id,
                    "version": item.record.version,
                    "status": item.status,
                    "content_hash": item.content_hash,
                }
                for item in revisions
            ],
        },
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    save_once(REPORTS / f"local-import-{stamp}.json", encoded(audit))
    return {key: value for key, value in audit.items() if key != "import"} | {
        "imported_count": audit["import"]["imported_count"],
        "unchanged_count": audit["import"]["unchanged_count"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-only", action="store_true")
    parser.add_argument(
        "--offline", action="store_true", help="只使用经 manifest 哈希核对的本地快照"
    )
    parser.add_argument(
        "--import-db", type=Path, help="显式指定本地 SQLite；只导入草稿并备份已有库"
    )
    args = parser.parse_args()
    if args.fetch_only and args.import_db:
        parser.error("--fetch-only 不能同时执行导入")
    if args.offline:
        manifest = json.loads((REPORTS / "source-manifest.json").read_text(encoding="utf-8"))
        if manifest["sources"] != SOURCES:
            raise ValueError("来源版本或配置已改变")
        files = manifest["files"]
        for item in files:
            data = source_path(item["source"], item["path"]).read_bytes()
            if sha256(data) != item["sha256"] or len(data) != item["bytes"]:
                raise ValueError("来源快照哈希不符，停止转换")
    else:
        files = fetch_sources()
    for item in files:
        if "LICENSING" in item["path"]:
            save_once(
                REPORTS / "licenses" / item["source"] / Path(item["path"]).name,
                source_path(item["source"], item["path"]).read_bytes(),
            )
    summary = {"downloaded_or_cached_files": len(files), "manifest": str(REPORTS)}
    if not args.fetch_only:
        report, cards = prepare_cards()
        summary.update(
            {
                key: value
                for key, value in report.items()
                if key not in {"index", "sensor_width_conflicts"}
            }
        )
    if args.import_db:
        summary["local_import"] = import_drafts(args.import_db, cards)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
