"""把已发布的器材参考资料接入选择器，不提升为已验证硬件能力。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from camera_assistant.models import CameraProfile, PhoneProfile
from camera_assistant.services.device_optics import lens_specifications, phone_lenses
from camera_assistant.services.phone_knowledge import normalized_model_name

# 只做明确名称归一化，不使用 Lensfun 的 compat 转接图推断兼容性。
MOUNT_LABELS = {
    "canon_rf": ("Canon RF",), "canon_ef": ("Canon EF", "Canon EF-S"),
    "nikon_z": ("Nikon Z",), "nikon_f": ("Nikon F", "Nikon F AF", "Nikon F AI"),
    "sony_e": ("Sony E", "Sony FE"), "sony_a": ("Sony Alpha", "Sony A", "Minolta AF"),
    "fujifilm_x": ("Fujifilm X", "Fuji X"),
    "micro_four_thirds": ("Micro Four Thirds", "Micro 4/3 System"),
    "leica_l": ("Leica L", "L-Mount"), "leica_m": ("Leica M",),
    "pentax_k": ("Pentax K", "Pentax KAF", "Pentax KAF2", "Pentax KAF3"),
    "canon_fd": ("Canon FD",), "four_thirds": ("Four Thirds", "4/3 System"),
}
MOUNT_KEYS = {normalized_model_name(label): key for key, labels in MOUNT_LABELS.items()
              for label in (key, *labels)}
BRANDS = {"huawei": ("Huawei", "华为"), "honor": ("HONOR", "荣耀"),
          "xiaomi": ("Xiaomi", "小米"), "redmi": ("REDMI", "红米"),
          "apple": ("Apple", "苹果"), "samsung": ("Samsung", "三星"),
          "vivo": ("vivo", "vivo"), "oppo": ("OPPO", "OPPO"), "iqoo": ("iQOO", "iQOO")}


def mount_key(label: str) -> str:
    return MOUNT_KEYS.get(normalized_model_name(label), "")


def camera_reference_mounts(camera: CameraProfile) -> set[str]:
    if camera.capability_level != "catalog":
        return {camera.mount} if camera.mount != "unknown" else set()
    return {key for label in camera.catalog_mount_labels if (key := mount_key(label))}


def reference_lenses_for(camera, lenses, declared_mount=""):
    mounts = camera_reference_mounts(camera)
    if not mounts and declared_mount in MOUNT_LABELS:
        mounts = {declared_mount}
    return [lens for lens in lenses if mounts.intersection(lens["mount_keys"])
            and (not lens.get("sensor_formats") or camera.sensor_format == "不清楚"
                 or camera.sensor_format in lens["sensor_formats"])]


def _identity(prefix, text):
    return prefix + hashlib.sha256(normalized_model_name(text).encode()).hexdigest()[:20]


def read_reference_devices(database: Path):
    phones, lenses = {}, {}
    if not database.is_file():
        return [], []
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        # 流式处理，避免同时构造整库历史修订及大型器材payload。
        for (raw,) in connection.execute("SELECT record_json FROM revisions "
                                        "WHERE library_id='equipment' AND status='published'"):
            record = json.loads(raw)
            if record.get("dataset_split") != "reference" or not record["source"].get("retrieval_allowed"):
                continue
            payload, source = record.get("payload", {}), record["source"]
            if record.get("conditions", {}).get("device_type") == "phone" and payload.get("model_variant"):
                model = payload["model_variant"]
                # 地区版本保留，不用同名跨区卡片相互补齐能力。
                region = payload.get("region_scope") or "地区待确认"
                identity = _identity("kb_phone_", model + ":" + region)
                if identity not in phones:
                    raw_brand = payload.get("brand") or "其他"
                    brand, chinese = BRANDS.get(raw_brand.casefold(), (raw_brand, raw_brand))
                    aliases = list(payload.get("aliases") or [])
                    if model.casefold().startswith(raw_brand.casefold()):
                        aliases.append(chinese + model[len(raw_brand):].lstrip())
                    entries = phone_lenses(payload.get("specifications") or {})
                    phones[identity] = PhoneProfile(profile_id=identity,
                        brand=brand, model=model, display_name=model,
                        aliases=aliases, lenses=entries,
                        source_urls=[source["url"]] if source.get("url") else [],
                        checked_at="", region_scope=region, capability_level="catalog",
                        knowledge_ids=[record["knowledge_id"]], notes=[
                            "型号来自已发布知识库，尚未完成独立实拍核验。",
                            "当前仅开启通用照片指导；未推断专业模式、变焦倍率或手动曝光范围。",
                        ], rear_camera_summary=str((payload.get("specifications") or {}).get("rear") or ""))
            if payload.get("entity_type") != "lens" or not payload.get("model"):
                continue  # 不把转接环、增距镜、针孔器材混进拍摄镜头。
            model = payload["model"]
            labels = payload.get("mounts") or []
            product = payload.get("source_product") or {}
            if not labels:
                labels = [product.get("mount", {}).get("systemId", "")]
            keys = sorted({key for label in labels if isinstance(label, str) and (key := mount_key(label))})
            if not keys:
                continue
            brand = payload.get("brand") or "其他"
            identity = _identity("kb_lens_", brand + ":" + model)
            specifications = lens_specifications(payload)
            if identity not in lenses:
                display = model if normalized_model_name(model).startswith(normalized_model_name(brand)) else f"{brand} {model}"
                lenses[identity] = {"reference_id": identity, "display_name": display, "retrieval_name": model,
                    "brand": brand, "mount_keys": keys,
                    "mount_labels": list(labels), "knowledge_ids": [record["knowledge_id"]],
                    "source_urls": [source["url"]] if source.get("url") else [],
                    "capability_level": "catalog", **specifications}
            else:
                item = lenses[identity]
                item["mount_keys"] = sorted(set(item["mount_keys"]) | set(keys))
                item["knowledge_ids"].append(record["knowledge_id"])
                if source.get("url") and source["url"] not in item["source_urls"]:
                    item["source_urls"].append(source["url"])
                fields = ("focal_min_mm", "focal_max_mm", "max_aperture_wide", "max_aperture_tele")
                if any(item.get(key) is not None and specifications.get(key) is not None
                       and item[key] != specifications[key] for key in fields):
                    item.update({key: None for key in fields})
                    item.update(parameter_linkage=False, controls_hardware_limits=False, specification_conflict=True)
                elif not item.get("specification_conflict"):
                    for key in fields:
                        if item.get(key) is None:
                            item[key] = specifications[key]
                    item["parameter_linkage"] = item.get("focal_min_mm") is not None
                    item["controls_hardware_limits"] = item["parameter_linkage"]
    return list(phones.values()), list(lenses.values())
