"""将社区相机草稿去重为非权威的可搜索目录；绝不审核或发布 RAG 草稿。"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from camera_assistant.knowledge.importer import parse_record_file

BATCH = "opensource-equipment-20261014"


def normalize(value: str) -> str:
    return re.sub(r"[\s_-]+", "", unicodedata.normalize("NFKC", value).casefold())


def qualified(brand: str, model: str) -> str:
    return model.strip() if normalize(model).startswith(normalize(brand)) else f"{brand} {model}"


def identity_names(record) -> tuple[str, list[str]]:
    raw_brand = record.payload["brand"]
    brand_aliases = {
        "nikoncorporation": "Nikon",
        "leicacameraag": "Leica",
        "minoltacoltd": "Minolta",
        "casio computer co.,ltd": "Casio",
        "eastmankodakcompany": "Kodak",
        "olympuscorporation": "Olympus",
        "olympusimagingcorp": "Olympus",
        "olympusopticalcoltd": "Olympus",
        "pentaxcorporation": "Pentax",
        "konicaminoltacamerainc": "Konica Minolta",
        "konicaminolta": "Konica Minolta",
        "samsungtechwin": "Samsung",
        "samsungtechwinco": "Samsung",
        "seiko epson corp": "Epson",
    }
    compact_brand = re.sub(r"[^a-z0-9]", "", normalize(raw_brand))
    lookup = {
        re.sub(r"[^a-z0-9]", "", normalize(key)): value for key, value in brand_aliases.items()
    }
    brand = lookup.get(compact_brand, raw_brand)
    names = [record.payload["model"], *record.payload.get("aliases", [])]
    if compact_brand in {"ricohimagingcompanyltd", "asahiopticalcoltd"}:
        if any("pentax" in normalize(name) for name in names):
            brand = "Pentax"
        elif any("ricoh" in normalize(name) for name in names):
            brand = "Ricoh"
    result = []
    for name in names:
        # 先去完整公司名称，再去重复品牌前缀，保留所有产品/版本后缀。
        for _ in range(3):
            old = name
            for prefix in sorted({raw_brand, brand}, key=len, reverse=True):
                name = re.sub(rf"^{re.escape(prefix)}\s+", "", name, flags=re.IGNORECASE)
            if name == old:
                break
        result.append(f"{brand} {name.strip()}")
    return brand, list(dict.fromkeys(result))


def serialize(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def build(root: Path = ROOT) -> tuple[dict, dict]:
    index = json.loads(
        (root / "knowledge_sources" / BATCH / "conversion-report.json").read_text(encoding="utf-8")
    )["index"]
    documents = []
    for item in index:
        if item["entity_type"] != "camera":
            continue
        path = root / "data/knowledge_drafts" / BATCH / item["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("相机来源文件与转换清单不符")
        documents.append(parse_record_file(path))
    curated = yaml.safe_load(
        (root / "knowledge/cameras/camera_profiles.yaml").read_text(encoding="utf-8")
    )["profiles"]
    curated = [item for item in curated if not item["profile_id"].startswith("generic_")]
    parents = list(range(len(documents)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parents[max(a, b)] = min(a, b)

    # 仅使用带品牌的完整名称和来源明示别名；不删掉 Pro、II、V 等版本后缀。
    aliases = defaultdict(list)
    for number, document in enumerate(documents):
        brand, names = identity_names(document)
        for name in names:
            aliases[(normalize(brand), normalize(qualified(brand, name)))].append(number)
    for numbers in aliases.values():
        for number in numbers[1:]:
            union(numbers[0], number)

    # 已有手工适配档案的显式别名可以归并来源组，但不得以相似型号继承能力。
    curated_matches = defaultdict(set)
    for profile in curated:
        matches = set()
        for name in [profile["display_name"], profile["model"], *profile.get("aliases", [])]:
            matches.update(
                aliases.get(
                    (normalize(profile["brand"]), normalize(qualified(profile["brand"], name))), []
                )
            )
        for number in matches:
            curated_matches[number].add(profile["profile_id"])
        if matches:
            first = min(matches)
            for number in matches:
                union(first, number)

    grouped = defaultdict(list)
    for number, document in enumerate(documents):
        grouped[find(number)].append((number, document))
    profiles = []
    exclusions = []
    merges = []
    curated_links = defaultdict(list)
    for group in grouped.values():
        records = [record for _, record in group]
        identities = [record.knowledge_id for record in records]
        reasons = []
        brands = {identity_names(record)[0] for record in records}
        if brands & {"Generic", "Apple", "Huawei", "Honor", "LG Mobile", "Microsoft", "Nokia"}:
            reasons.append("通用校正模板或手机/手机镜头记录，不发布为独立相机型号。")
        if any(
            check.get("status") in {"conflict", "ambiguous_model"}
            for record in records
            for check in record.payload.get("consistency_checks", [])
        ):
            reasons.append("传感器来源存在冲突或完整型号歧义，需补充年份及地区后复核。")
        matched = set().union(*(curated_matches[number] for number, _ in group))
        if len(matched) > 1:
            reasons.append("同一来源组命中多个已有适配档案。")
        if reasons:
            exclusions.append(
                {
                    "source_ids": identities,
                    "models": [r.payload["model"] for r in records],
                    "reasons": reasons,
                }
            )
            continue
        if len(records) > 1:
            merges.append(
                {"source_ids": identities, "rule": "same_brand_and_complete_name_or_explicit_alias"}
            )
        if matched:
            curated_links[next(iter(matched))].extend(identities)
            continue
        preferred = min(
            records,
            key=lambda record: (
                record.payload["provenance"]["repository"].endswith("lensfun/lensfun"),
                record.payload["model"],
                record.knowledge_id,
            ),
        )
        brand, preferred_names = identity_names(preferred)
        model = preferred_names[0]
        names = sorted({name for record in records for name in identity_names(record)[1]})
        sizes = sorted(
            {
                str(record.payload.get("source_specs", {}).get("Sensor size"))
                for record in records
                if record.payload.get("source_specs", {}).get("Sensor size")
            }
        )
        mounts = sorted({mount for record in records for mount in record.payload.get("mounts", [])})
        sources = []
        for record in records:
            origin = record.payload["provenance"]
            sources.append(
                {
                    "knowledge_id": record.knowledge_id,
                    "url": record.source.url,
                    "license": record.source.license,
                    "attribution": origin["attribution"],
                    "commit": origin["commit"],
                }
            )
        # 此文件是可选机型目录，不是硬件规格批准表。社区规格仅作为待核验文本展示。
        digest = hashlib.sha256((normalize(brand) + "\0" + normalize(model)).encode()).hexdigest()[
            :20
        ]
        profiles.append(
            {
                "profile_id": f"catalog_{digest}",
                "brand": brand,
                "model": model[len(brand) :].strip()
                if model.casefold().startswith(brand.casefold() + " ")
                else model,
                "display_name": model,
                "aliases": names,
                "capability_level": "catalog",
                "sensor_format": "不清楚",
                "crop_factor": None,
                "mount": "unknown",
                "catalog_sensor_label": " / ".join(sizes),
                "catalog_mount_labels": mounts,
                "catalog_sources": sources,
                "catalog_source_ids": identities,
                "source_url": preferred.source.url,
                "notes": [
                    "仅发布为基础设备目录，尚未完成硬件能力核验；来源规格不能直接用作调参边界。"
                ],
                "aperture_priority_name": "机内可用曝光模式（能力未核验）",
                "shutter_priority_name": "机内可用曝光模式（能力未核验）",
                "continuous_focus_name": "机内可用对焦方式（能力未核验）",
                "single_focus_name": "机内可用对焦方式（能力未核验）",
                "metering_name": "机内可用测光方式（能力未核验）",
            }
        )
    profiles.sort(key=lambda item: (item["brand"].casefold(), item["display_name"].casefold()))
    ids = [item["profile_id"] for item in profiles]
    if len(set(ids)) != len(ids):
        raise ValueError("目录身份发生重复，请人工复核")
    report = {
        "source_camera_records": len(documents),
        "name_groups": len(grouped),
        "merged_groups": len(merges),
        "merged_source_records": sum(len(g["source_ids"]) - 1 for g in merges),
        "catalog_only_cameras": len(profiles),
        "adapted_cameras": len(curated),
        "searchable_cameras": len(profiles) + len(curated),
        "excluded_groups": exclusions,
        "curated_links": dict(curated_links),
        "merges": merges,
        "brands": dict(Counter(item["brand"] for item in profiles)),
        "all_hardware_boundaries_unknown_for_catalog_only": True,
        "rag_review_or_publication_performed": False,
        "identity_limit": "同品牌完整名称和明确别名去重；不是所有地区名称的全自动实体核验。",
    }
    catalog = {
        "schema_version": 1,
        "kind": "camera_directory",
        "release_date": "2026-10-15",
        "license": "CC-BY-SA-3.0",
        "license_notice": "catalog_licenses/NOTICE.txt",
        "catalog_only_count": len(profiles),
        "profiles": profiles,
        "curated_links": dict(curated_links),
        "usage": "基础目录可选，不代表厂家核验；原 RAG 草稿状态不变。",
    }
    return catalog, report


def main() -> None:
    catalog, report = build()
    directory = ROOT / "knowledge/cameras"
    # 机械构建产物；人工资料仍保留在 camera_profiles.yaml，绝不写回原始草稿。
    (directory / "camera_catalog.json").write_bytes(serialize(catalog))
    licenses = directory / "catalog_licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    upstream = ROOT / "knowledge_sources" / BATCH / "licenses"
    for source, target in (
        ("cameradatabase/LICENSE", "CameraDatabase-MIT.txt"),
        ("lensfun/COPYING.CC_BY-SA_3.0", "Lensfun-CC-BY-SA-3.0.txt"),
    ):
        (licenses / target).write_bytes((upstream / source).read_bytes())
    (licenses / "NOTICE.txt").write_text(
        "Camera directory derived from CameraDatabase (MIT, copyright 2025 leavestylecode) "
        "and the Lensfun database (CC BY-SA 3.0, Lensfun contributors).\n"
        "Upstream: https://github.com/leavestylecode/CameraDatabase and "
        "https://github.com/lensfun/lensfun .\n"
        "Modifications by Xiaoli Camera Assistant, 2026-10-15: normalized brand/company names, "
        "merged exact full-name/explicit-alias duplicates, quarantined ambiguous records, "
        "and removed unverified hardware capability boundaries.\n"
        "This derived camera_catalog.json is distributed under CC BY-SA 3.0 "
        "(https://creativecommons.org/licenses/by-sa/3.0/). "
        "Original MIT notices remain in CameraDatabase-MIT.txt. "
        "Per-record catalog_sources retain source URLs, attribution, licenses and revisions.\n"
        "No endorsement by the upstream projects or camera manufacturers is implied.\n",
        encoding="utf-8",
    )
    destination = ROOT / "knowledge_sources/camera-catalog-release-20261015"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "deduplication.json").write_bytes(serialize(report))
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key not in {"merges", "curated_links", "brands", "excluded_groups"}
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
