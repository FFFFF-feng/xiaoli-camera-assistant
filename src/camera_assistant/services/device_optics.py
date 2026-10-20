"""将资料中的显式光学字段转换为选择项；不从校正采样或变焦倍率猜规格。"""
from __future__ import annotations

import math
import re

from camera_assistant.models import PhoneLens


def number(value, low, high):
    return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and low <= value <= high else None)


def lens_specifications(payload):
    product = payload.get("source_product") or {}
    optical = product.get("lens") or {}
    focal = optical.get("focalLength") or {}
    lo = hi = None
    if focal.get("kind") == "prime":
        lo = hi = number(focal.get("millimeters"), 8, 1200)
    elif focal.get("kind") == "zoom":
        span = focal.get("rangeMm") or {}
        lo, hi = number(span.get("minimum"), 8, 1200), number(span.get("maximum"), 8, 1200)
    wide = tele = None
    limits = ((optical.get("aperture") or {}).get("fNumber") or {}).get("maximumAperture") or []
    for limit in limits:
        aperture = number(limit.get("value"), .7, 32)
        conditions = limit.get("conditions") or {}
        if aperture is not None and not conditions:
            wide = tele = aperture
        elif aperture is not None:
            point = conditions.get("focalLength") or {}
            if point.get("kind") == "point":
                if point.get("millimeters") == lo:
                    wide = aperture
                if point.get("millimeters") == hi:
                    tele = aperture
    basis = "structured_source"
    # Lensfun 的校正采样不代表光学端点；只解析型号中明写的 mm 与 F 标称值。
    if not optical:
        text = payload.get("model", "")
        span = re.search(r"(\d+(?:\.\d+)?)\s*(?:[-–—]\s*(\d+(?:\.\d+)?))?\s*mm\b", text, re.IGNORECASE)
        opening = re.search(r"(?<![a-z])f\s*/?\s*(\d+(?:\.\d+)?)\s*(?:[-–—]\s*(\d+(?:\.\d+)?))?", text, re.IGNORECASE)
        if span:
            lo, hi = (number(float(span[1]), 8, 1200), number(float(span[2] or span[1]), 8, 1200))
        if opening:
            wide, tele = (number(float(opening[1]), .7, 32), number(float(opening[2] or opening[1]), .7, 32))
        basis = "explicit_model_label"
    if lo is None or hi is None or lo > hi or not lo.is_integer() or not hi.is_integer():
        lo = hi = None  # 当前应用请求只支持整毫米，不四舍五入改写规格。
    if wide is None or tele is None or wide > tele:
        wide = tele = None
    coverage = (optical.get("coverage") or {}).get("format")
    formats = {"full-frame": ["全画幅", "APS-C"], "aps-c": ["APS-C"],
               "micro-four-thirds": ["M4/3"]}.get(coverage, [])
    return {"focal_min_mm": int(lo) if lo is not None else None,
            "focal_max_mm": int(hi) if hi is not None else None,
            "max_aperture_wide": wide, "max_aperture_tele": tele,
            "sensor_formats": formats, "specification_basis": basis,
            "parameter_linkage": lo is not None,
            "controls_hardware_limits": lo is not None}


def _role(text):
    if re.search(r"数字|数码|裁切|前置|景深|黑白|光谱|原色摄像", text):
        return None
    if re.search(r"超广角|超视野|超广视", text):
        return "ultrawide", "超广角"
    if re.search(r"潜望|长焦|远摄", text):
        return "telephoto", "长焦"
    if re.search(r"微距", text) and "主摄" not in text:
        return "macro", "微距"
    if "人像主摄" in text:
        return "portrait", "人像镜头"
    if re.search(r"主摄|超光变摄像|(?<!超)广角摄像|广角镜头", text):
        return "main", "主摄"
    return None


def phone_lenses(specifications):
    entries = {}
    structured = (specifications.get("cameras") or {}).get("rear_entries") or []
    for index, item in enumerate(structured if isinstance(structured, list) else []):
        role = _role(item.get("role", ""))
        if not role:
            continue
        key, title = role
        aperture = number(item.get("aperture_f_number"), .7, 32)
        span = item.get("aperture_f_number_range")
        if isinstance(span, list) and len(span) == 2:
            low, high = number(span[0], .7, 32), number(span[1], .7, 32)
            if low is not None and high is not None and low <= high:
                aperture = low
            else:
                high = None
        else:
            high = None
        identity = "main" if key == "main" else f"rear_{index}"
        entries[key] = PhoneLens(lens_id=identity, name=title, aperture=aperture,
            aperture_max=high, aperture_control="unknown",
            notes=["来源结构化规格；未证明手动光圈入口或镜头与模式的完整组合。"])
    raw = specifications.get("rear")
    if isinstance(raw, str):
        # 分号、换行分摄像头；加号也可能连接光圈字段，因此只在加号后出现像素/角色时分段。
        segments = re.split(r"[；;\n]+|[+＋](?=\s*(?:\d+(?:\.\d+)?\s*(?:万|亿|[MmWw])|主摄|超广角|长焦|潜望|微距))", raw)
        # 无分隔符的列表，只有明确摄像头角色才拆；不从“三摄/双摄”生成数量。
        for segment in segments:
            marks = list(re.finditer(r"超广角(?:[/／]?微距)?(?:主摄|摄像头|镜头)?|潜望(?:式)?(?:长焦)?(?:摄像头|镜头)?|(?<!潜望)长焦(?:摄像头|镜头)?|人像主摄|主摄(?:像头)?|微距(?:摄像头|镜头)?", segment))
            pieces = [segment] if len(marks) <= 1 else [segment[m.start():marks[i+1].start() if i+1 < len(marks) else len(segment)] for i,m in enumerate(marks)]
            # “超广角微距”是同一摄像头，不能拆成两颗；主摄/广角同理。
            if re.search(r"超广角\s*[/／]?\s*微距", segment):
                pieces = [segment]
            if "按厂商顺序" in segment:
                pieces = re.findall(r"[fFƒ]\s*/?\s*\d+(?:\.\d+)?\s*[（(][^（）()]+[）)]", segment)
            for piece in pieces:
                role = _role(piece)
                if not role:
                    continue
                key, title = role
                if key in entries:
                    # 后续“按厂商顺序：f/...（主摄）”补充同一角色，不新造一颗镜头。
                    lens = entries[key]
                else:
                    lens = PhoneLens(lens_id="main" if key == "main" else key, name=title,
                                     notes=["按来源后置摄像头文字字段整理；实际可选镜头以本机相机为准。"])
                    entries[key] = lens
                opening = re.search(r"[fFƒ]\s*/?\s*(\d+(?:\.\d+)?)(?:\s*[-–—]\s*[fFƒ]?\s*/?\s*(\d+(?:\.\d+)?))?", piece)
                if opening and lens.aperture is None:
                    low = number(float(opening[1]), .7, 32)
                    high = number(float(opening[2]), .7, 32) if opening[2] else None
                    if low is not None and (high is None or high >= low):
                        lens.aperture, lens.aperture_max = low, high
                equivalent = re.search(r"等效(?:焦距)?\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)|\b(\d+(?:\.\d+)?)\s*mm\s*等效", piece, re.IGNORECASE)
                if equivalent:
                    lens.equivalent_focal_length_mm = number(float(equivalent[1] or equivalent[2]), 5, 1000)
    if "main" not in entries:
        entries["main"] = PhoneLens(lens_id="main", name="主摄（来源规格未完整提取）")
    return [entries["main"], *[lens for key,lens in entries.items() if key != "main"]]
