"""Prepare an immutable, offline human confirmation package from saved AI drafts.

Only saved files, the current DetectorReference contract, and Pillow are used.
No runner, detector worker, model client, API, or download is imported or invoked.
Existing identical artifacts are reused; any different existing bytes abort the
whole export before writing. Choose a new --output for a revised package.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import os
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageFont, ImageOps

from vision_lab_tool.detector_models import DetectorExperiment, DetectorReference

SAMPLES = ("B02", "D03", "D07", "C03", "P06")
PACKAGE_VERSION = "ai-confirmation-package-v1"
LEVELS = {"whole": "整体", "part": "部件", "instance": "实例", "region": "区域",
          "combination": "组合", "unknown": "未知"}
ENTITIES = {"physical": "现场实体", "depiction": "描绘实体", "reflection": "反射",
            "mannequin": "人偶", "scale_model": "比例模型", "unknown": "未知"}
NAMES = {
    "B02_cup_whole": "水杯整体", "B02_content_visible": "杯中可见内容区域",
    "B02_opening_visible": "杯口内视区域（独立备选解释）",
    "D03_tool_whole": "金属器具整体", "D03_body": "盒体", "D03_rod": "上方细杆",
    "D03_tube_top": "右伸第1根管（最上）", "D03_tube_second": "右伸第2根管",
    "D03_tube_third": "右伸第3根管", "D03_tube_bottom": "右伸第4根管（最下）",
    "D03_body_opening": "盒体开口内区域", "D03_tubes_combination": "四根管的组合范围",
    "D07_hand_upper": "上方手", "D07_hand_lower": "下方手",
    "D07_clay_visible": "泥坯可见整体", "D07_wheel_visible": "陶轮可见轮面区域",
    "C03_billboard_context": "广告牌上下文", "C03_depicted_person": "广告中人物候选",
    "P06_person_central_left": "平台尖端左侧人物", "P06_person_central_right": "平台尖端右侧人物",
    "P06_person_middle_left": "中部双人左侧", "P06_person_middle_right": "中部双人右侧",
    "P06_person_foreground_shadow": "左侧前景阴影处人物",
    "P06_person_foreground_yellow": "左侧前景黄色片段人物",
    "P06_person_rear_pink": "左侧后排粉色人物", "P06_person_rear_dark": "左侧后排深色人物",
    "P06_person_rear_upper_left": "后排上方左侧人物",
    "P06_person_rear_upper_right": "后排上方右侧人物", "P06_person_rear_seated": "后排坐姿人物",
    "P06_person_uncertain_cluster": "后排不稳定人物簇（人数待定）",
    "P06_possible_person_blue_fragment": "左后方疑似蓝色人物片段",
    "P06_ledge_context": "岩台尺度上下文",
}
CUES = {
    "D07_hand_upper": "确认上方手的指尖、掌缘和腕界，避免把前臂算入；手指归属是否正确？",
    "D07_hand_lower": "确认下方手的指尖、掌缘和腕界，与上方手分别划界。",
    "D07_clay_visible": "确认被手遮住的泥坯可见范围；浅色下缘是否混入承托盘？",
    "D07_wheel_visible": "确认轮面范围：仅转动盘面，还是包含可见下缘？",
    "C03_billboard_context": "确认是否作为描绘人物的父对象；上下文是否需要独立评判？",
    "C03_depicted_person": "确认是哪一个人物、是否描绘实体；边界是否包含所持卡片？",
    "P06_person_uncertain_cluster": "确认是否有人、可辨人数及能否拆成实例；无法判定可保留ignore及理由。",
    "P06_possible_person_blue_fragment": "确认是人物还是背包/衣物；边界/实体无法判定可保留未知。",
    "P06_ledge_context": "确认尺度上下文范围；不得用岩台框替代人物实例。",
}
COLORS = ("#e11d48", "#2563eb", "#059669", "#d97706", "#7c3aed", "#0891b2",
          "#c026d3", "#65a30d", "#ea580c", "#4f46e5", "#0d9488", "#be123c",
          "#a16207", "#4338ca")
STYLE = """body{font-family:system-ui,sans-serif;max-width:1400px;margin:24px auto;padding:0 20px;
color:#172033;background:#fafafa;line-height:1.55}a{color:#164fc7}section{margin:36px 0;
padding:24px;background:white;border:1px solid #ddd;border-radius:12px}h1,h2,h3{line-height:1.25}
.images{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}figure{margin:0}
img{max-width:100%;height:auto}figcaption{font-size:14px}table{border-collapse:collapse;width:100%;
font-size:14px}td,th{border:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}
code{overflow-wrap:anywhere}.notice{padding:12px;background:#fff1d6}details{margin:16px 0}
@media(max-width:700px){.images{grid-template-columns:1fr}section{padding:12px}.scroll{overflow:auto}}
"""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def relative_link(path: Path, output: Path) -> str:
    return esc(quote(os.path.relpath(path, output).replace(os.sep, "/"), safe="/"))


def document(title: str, body: str) -> bytes:
    return (f'<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><style>{STYLE}</style><body>{body}</body></html>').encode()


def numbered_overlay(image, numbered_objects) -> bytes:
    """Draw numbered evidence boxes without changing any draft coordinates."""
    canvas = image.convert("RGB").copy()
    draw = ImageDraw.Draw(canvas)
    width, height = canvas.size
    size = max(14, min(width, height) // 45)
    font = ImageFont.load_default(size=size)
    occupied = []
    for number, obj in numbered_objects:
        x0, y0, x1, y1 = [v * size_ for v, size_ in
                           zip(obj.bbox, (width, height, width, height))]
        color = COLORS[(number - 1) % len(COLORS)]
        draw.rectangle((x0, y0, min(x1, width - 1), min(y1, height - 1)),
                       outline=color, width=max(2, min(width, height) // 350))
        label = str(number)
        bounds = draw.textbbox((0, 0), label, font=font)
        label_width, label_height = bounds[2] + 10, size + 10
        tag_x = max(0, min(int(x0), width - label_width))
        tag_y = max(0, min(int(y0) - label_height, height - label_height))
        for _ in range(len(numbered_objects) + 1):
            rect = (tag_x, tag_y, tag_x + label_width, tag_y + label_height)
            if not any(rect[0] < r[2] and rect[2] > r[0] and
                       rect[1] < r[3] and rect[3] > r[1] for r in occupied):
                break
            tag_y += label_height + 3
            if tag_y > height - label_height:
                tag_y = 0
                tag_x = max(0, min(tag_x + label_width + 3, width - label_width))
        occupied.append((tag_x, tag_y, tag_x + label_width, tag_y + label_height))
        draw.line((x0, y0, tag_x + label_width // 2, tag_y + label_height // 2),
                  fill=color, width=1)
        draw.rectangle(occupied[-1], fill=color)
        draw.text((tag_x + 5, tag_y + 3), label, fill="white", font=font)
    buffer = io.BytesIO()
    canvas.save(buffer, "PNG")
    return buffer.getvalue()


def focus_overlay(image, number, obj) -> bytes:
    """Show one draft at original resolution before enlarging a context crop."""
    with Image.open(io.BytesIO(numbered_overlay(image, [(number, obj)]))) as marked:
        width, height = marked.size
        x0, y0, x1, y1 = obj.bbox
        pad_x = max(.035, (x1 - x0) * .5)
        pad_y = max(.035, (y1 - y0) * .5)
        crop = marked.crop((max(0, int((x0 - pad_x) * width)),
                            max(0, int((y0 - pad_y) * height)),
                            min(width, int((x1 + pad_x) * width) + 1),
                            min(height, int((y1 + pad_y) * height) + 1)))
        scale = 640 / max(crop.size)
        crop = crop.resize(tuple(max(1, round(v * scale)) for v in crop.size),
                           Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        crop.save(buffer, "PNG")
        return buffer.getvalue()


def confirmation_rows(sample, reference, draft):
    numbers = {obj.gt_id: index for index, obj in enumerate(reference.objects, 1)}
    rows = []
    for number, obj in enumerate(reference.objects, 1):
        scope = "必需" if obj.required else "可选"
        if obj.out_of_scope:
            scope += "；范围外上下文"
        if obj.ignore:
            scope += "；ignore草稿，保留原范围/理由"
        cue = draft.get("review_cues", {}).get(obj.gt_id, CUES.get(obj.gt_id, ""))
        if not cue:
            cue = "逐一确认是否存在、是哪一个以及可见边界；核对遮挡，追加遗漏实例。"
        rows.append({
            "sample_id": sample, "number": number, "gt_id": obj.gt_id,
            "object_zh": NAMES.get(obj.gt_id, obj.label), "label": obj.label,
            "bbox_normalized_xyxy": obj.bbox, "target_level": obj.target_level,
            "parent_number": numbers.get(obj.parent_id), "entity_kind": obj.entity_kind,
            "required": obj.required, "user_main_subject": obj.user_main_subject,
            "ignore": obj.ignore, "ignore_reason": obj.ignore_reason,
            "out_of_scope": obj.out_of_scope, "draft_scope_zh": scope,
            "confirmation_cue_zh": cue, "user_original_confirmation": "",
            "field_confirmation": "", "revision_reason": "",
            "annotation_source": "ai", "confirmed": False,
        })
    return rows


def csv_bytes(rows) -> bytes:
    buffer = io.StringIO(newline="")
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            cells = {}
            for key, value in row.items():
                text = json.dumps(value, ensure_ascii=False) if isinstance(value, list) else str(
                    value if value is not None else "")
                cells[key] = "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text
            writer.writerow(cells)
    return buffer.getvalue().encode("utf-8-sig")


def prepare_package(source: Path, output: Path, samples=SAMPLES) -> dict:
    """Validate frozen inputs, build all artifacts, then exclusively write new files."""
    source, output = Path(source).resolve(), Path(output).resolve()
    if output == source or source in output.parents:
        raise ValueError("Output must be outside the immutable source experiment")
    samples = tuple(samples)
    if len(set(samples)) != len(samples) or any(sample not in SAMPLES for sample in samples):
        raise ValueError("Unknown or duplicate confirmation sample")
    source_hashes, artifacts = {}, {}

    def read(path):
        data = path.read_bytes()
        source_hashes[str(path)] = sha(data)
        return data

    drafts = {}
    for path in sorted((source / "ai_references").glob("*.json")):
        draft = json.loads(read(path))
        reference = DetectorReference.model_validate(draft["reference"])
        if (reference.complete or draft.get("annotation_source") != "ai" or
                draft.get("confirmed") is not False or draft.get("complete") is not False or
                any(obj.confirmed or obj.annotation_source != "ai" for obj in reference.objects)):
            raise ValueError(f"{path.stem}: source must remain an unconfirmed AI draft")
        drafts[path.stem] = (draft, reference)
    all_draft_objects = sum(len(ref.objects) for _, ref in drafts.values())
    manifests, all_rows, run_rows, sections = [], [], [], []
    for sample in samples:
        draft, reference = drafts[sample]
        folder = source / "inputs" / sample
        input_path = folder / "input.json"
        metadata = json.loads(read(input_path))
        if draft["sample_id"] != sample or draft["task_prompt"] != metadata["task_prompt"]:
            raise ValueError(f"{sample}: draft task does not match the complete saved task")
        images = {}
        for name, hash_key, size_key in [
            ("original.jpg", "original_sha256", "original_size"),
            ("sent.jpg", "sent_sha256", "sent_size"),
            ("corrected.png", "corrected_sha256", "corrected_size"),
        ]:
            data = read(folder / name)
            if name != "corrected.png" and sha(data) != metadata[hash_key]:
                raise ValueError(f"{sample}: {name} hash mismatch")
            declared = draft.get("input_hashes", {}).get(hash_key)
            if declared is not None and declared != metadata[hash_key]:
                raise ValueError(f"{sample}: draft {hash_key} mismatch")
            with Image.open(io.BytesIO(data)) as image:
                if list(image.size) != metadata[size_key]:
                    raise ValueError(f"{sample}: {name} size mismatch")
                images[name] = ImageOps.exif_transpose(image).convert("RGB")
                if name == "corrected.png" and sha(
                    str(images[name].size).encode() + images[name].tobytes()
                ) != metadata[hash_key]:
                    raise ValueError(f"{sample}: {name} corrected pixel hash mismatch")
            artifacts[f"{sample}/{name}"] = data
        if images["original.jpg"].size != images["corrected.png"].size:
            raise ValueError(f"{sample}: EXIF corrected original size mismatch")
        artifacts[f"{sample}/reference.json"] = json_bytes(reference.model_dump(mode="json"))
        numbered = list(enumerate(reference.objects, 1))
        artifacts[f"{sample}/reference_original.png"] = numbered_overlay(
            images["original.jpg"], numbered)
        artifacts[f"{sample}/reference_sent.png"] = numbered_overlay(images["sent.jpg"], numbered)
        rows = confirmation_rows(sample, reference, draft)
        all_rows.extend(rows)
        artifacts[f"{sample}/confirmation_table.json"] = json_bytes(rows)
        artifacts[f"{sample}/confirmation_table.csv"] = csv_bytes(rows)
        for number, obj in numbered:
            artifacts[f"{sample}/focus_{number:02}.png"] = focus_overlay(
                images["original.jpg"], number, obj)
        mapping = []
        paths = sorted((source / "outputs").glob(f"*/{sample}/*/run.json"),
                       key=lambda p: (p.parts[-4] != "v1", p.parts[-4], p.parts[-2]))
        for path in paths:
            run_data = read(path)
            run = DetectorExperiment.model_validate_json(run_data)
            if run.task_prompt != metadata["task_prompt"]:
                raise ValueError(f"{sample}: source run task differs from the full shared task")
            if any(run.image.get(key) != metadata[key] for key in
                   ("original_sha256", "sent_sha256")):
                raise ValueError(f"{sample}: source run image hashes differ")
            version, condition = path.parts[-4], path.parts[-2]
            for result in run.results:
                name = result.method if result.method != "detector_only" else (
                    result.method + "_" + result.detector)
                overlay_path = path.parent / f"{name}_overlay.jpg"
                if overlay_path.exists():
                    read(overlay_path)
                row = {
                    "sample_id": sample, "version": version, "condition": condition,
                    "run_id": run.run_id, "experiment_version": run.experiment_version,
                    "method": result.method, "detector": result.detector,
                    "result_id": result.result_id, "status": result.status,
                    "selection_status": result.selection.status,
                    "source_run_path": str(path), "source_run_sha256": sha(run_data),
                    "store_run_path": str(source.parent / "runs" / f"{run.run_id}.json"),
                    "sample_path": str(source.parent / "samples" / (run.sample_file or "")),
                    "original_path": str(folder / "original.jpg"),
                    "sent_path": str(folder / "sent.jpg"),
                    "reference_json_path": str(output / sample / "reference.json"),
                    "prediction_overlay_path": str(overlay_path) if overlay_path.exists() else None,
                    "recommended_initial": version == "v1" and condition == "paired",
                }
                mapping.append(row)
                run_rows.append(row)
        if not mapping:
            raise ValueError(f"{sample}: no saved runs to reopen")
        manifest = {
            "package_version": PACKAGE_VERSION, "sample_id": sample,
            "evaluation_scope": "original_full_shared_task", "blind_test": False,
            "task_prompt": metadata["task_prompt"],
            "task_prompt_sha256": sha(metadata["task_prompt"].encode("utf-8")),
            "input": metadata, "input_json_path": str(input_path),
            "corrected_sha256_basis": "str(RGB.size).encode() + RGB.tobytes()",
            "corrected_png_file_sha256": source_hashes[str(folder / "corrected.png")],
            "input_json_sha256": source_hashes[str(input_path)],
            "ai_draft_path": str(source / "ai_references" / f"{sample}.json"),
            "ai_draft_sha256": source_hashes[str(source / "ai_references" / f"{sample}.json")],
            "annotation_source": "ai", "confirmed": False, "complete": False,
            "reference_file": f"{sample}/reference.json", "pending_objects": len(rows),
            "required_objects": sum(obj.required for obj in reference.objects),
            "ignore_objects": sum(obj.ignore for obj in reference.objects),
            "out_of_scope_objects": sum(obj.out_of_scope for obj in reference.objects),
            "unresolved_instance_counts": draft.get("unresolved_instance_counts", []),
            "disputed_questions": draft.get("disputed_questions", []),
            "ai_draft_metadata": {k: v for k, v in draft.items() if k != "reference"},
            "source_runs": mapping,
        }
        manifests.append(manifest)
        artifacts[f"{sample}/manifest.json"] = json_bytes(manifest)
        questions = "".join(f"<li>{esc(q)}</li>" for q in manifest["disputed_questions"])
        body_rows = []
        for row in rows:
            number = row["number"]
            parent = row["parent_number"] or "无"
            body_rows.append(
                f'<tr><td><a href="{sample}/focus_{number:02}.png">{number} · 放大</a></td>'
                f'<td>{esc(row["object_zh"])}<br><code>{esc(row["gt_id"])}</code>'
                f'<br>{esc(row["label"])}</td><td>{esc(row["draft_scope_zh"])}</td>'
                f'<td>{esc(LEVELS[row["target_level"]])}<br>父编号：{parent}</td>'
                f'<td>{esc(ENTITIES[row["entity_kind"]])}（AI）</td>'
                f'<td>{esc(row["confirmation_cue_zh"])}<br>主目标/必需、层级、实体是否同意；'
                '不能判定可写未知。</td><td>待用户逐项回复</td></tr>')
        sections.append(
            f'<section id="{sample}"><h2>{sample} · {len(rows)}项待确认</h2>'
            f'<p><strong>原完整任务：</strong>{esc(metadata["task_prompt"])}</p>'
            f'<p><a href="{sample}/reference.json">可直接导入的参考框 JSON</a> · '
            f'<a href="{sample}/confirmation_table.csv">逐项确认表 CSV</a> · '
            f'<a href="{sample}/manifest.json">来源、哈希及未决范围</a></p>'
            '<div class="images">'
            f'<figure><a href="{sample}/reference_original.png"><img '
            f'src="{sample}/reference_original.png" alt="{sample} 原图AI草稿编号叠框"></a>'
            '<figcaption>方向修正原图上的AI草稿；坐标与原图细节优先。</figcaption></figure>'
            f'<figure><a href="{sample}/reference_sent.png"><img '
            f'src="{sample}/reference_sent.png" alt="{sample} 发送图AI草稿编号叠框"></a>'
            '<figcaption>实际发送JPEG上的同一草稿，编号不变。</figcaption></figure></div>'
            f'<details><summary>查看无框原图 / 实际发送图</summary><div class="images">'
            f'<figure><img src="{sample}/corrected.png" alt="{sample} 无框方向修正原图">'
            f'<figcaption><a href="{sample}/original.jpg">原始字节照片</a> · '
            f'{esc(metadata["original_size"])} · SHA256 '
            f'<code>{metadata["original_sha256"]}</code></figcaption></figure>'
            f'<figure><img src="{sample}/sent.jpg" alt="{sample} 实际发送图">'
            f'<figcaption>{esc(metadata["sent_size"])} · SHA256 '
            f'<code>{metadata["sent_sha256"]}</code></figcaption></figure></div></details>'
            f'<ul>{questions}</ul><div class="scroll"><table><tr><th>编号</th><th>对象草稿</th>'
            '<th>任务范围草稿</th><th>层级</th><th>实体归属</th><th>用户确认要点</th>'
            f'<th>确认</th></tr>{"".join(body_rows)}</table></div>'
            '<p>回复示例：B02-1存在，整体边界确认，主目标且必需，现场实体；'
            'B02-2边界需改……。未提及的字段和对象继续待确认。</p></section>')
    artifacts["source_runs.json"] = json_bytes({"package_version": PACKAGE_VERSION, "rows": run_rows})
    artifacts["source_runs.csv"] = csv_bytes(run_rows)
    artifacts["confirmation_table.csv"] = csv_bytes(all_rows)
    prediction_sections = []
    for row in run_rows:
        overlay = row["prediction_overlay_path"]
        img = (f'<img src="{relative_link(Path(overlay), output)}" loading="lazy" '
               'alt="已有模型候选叠框">' if overlay else '<p>本记录未保存预测叠框。</p>')
        prediction_sections.append(
            f'<section><h2>{row["sample_id"]} · {esc(row["version"])} · '
            f'{esc(row["condition"])} · {esc(row["method"])} {esc(row["detector"])}</h2>'
            f'<p>run_id：<code>{row["run_id"]}</code>；result_id：'
            f'<code>{row["result_id"]}</code>；状态：{esc(row["status"])}；'
            f'自动关联：{esc(row["selection_status"])}</p>{img}'
            f'<p><a href="{relative_link(Path(row["source_run_path"]), output)}">'
            '已有run JSON（只读来源）</a></p></section>')
    artifacts["predictions.html"] = document(
        "模型预测独立结果视图", '<h1>已有模型预测 · 独立结果视图</h1>'
        '<p class="notice">这些框是已有模型输出，全部照片事实仍待确认。'
        '此视图不会导入预测作为参考，也不发起推理。</p><p><a href="index.html">'
        '返回原图与AI参考草稿</a></p>' + "".join(prediction_sections))
    navigation = " · ".join(f'<a href="#{s}">{s}</a>' for s in samples)
    pending = sum(m["pending_objects"] for m in manifests)
    artifacts["index.html"] = document(
        "5图人工确认包 · B02先看", '<h1>定位人工确认包 · 从B02开始</h1>'
        f'<p>{navigation}</p><p class="notice">{pending}项均为AI预标注：'
        'annotation_source=ai、confirmed=false、complete=false。图片已有曝光，'
        '用于已有结果诊断；人工定位质量继续未评测。</p>'
        '<p>每项请判断：是否存在/是哪一个、边界是否完整或怎样改、整体/部件/实例/区域、'
        '主目标及是否必需、实体归属或无法判定。ignore也是待确认范围，不能隐藏难目标。</p>'
        '<p>在测试工具“检测与联合定位”重开对应派生记录，展开“批量导入 / 编辑参考 JSON”，'
        '粘贴本包对应reference.json后点“应用参考 JSON”；只使用参考区确认。'
        '编辑后保存到新参考版本及确认日志。部分确认保留其余项目，保持complete=false。'
        '当前完整质量指标不支持部分参考评分。</p>'
        '<p><a href="source_runs.csv">具体旧记录映射（run_id、版本、方法、图片路径）</a> · '
        '<a href="source_runs.json">映射JSON</a> · '
        '<a href="predictions.html">单独查看已有模型预测</a></p>' + "".join(sections))
    result = {
        "package_version": PACKAGE_VERSION, "source_experiment": str(source),
        "output_directory": str(output), "sample_order": list(samples),
        "all_ai_draft_objects": all_draft_objects, "pending_objects": pending,
        "required_objects": sum(m["required_objects"] for m in manifests),
        "ignore_objects": sum(m["ignore_objects"] for m in manifests),
        "source_run_count": len({r["run_id"] for r in run_rows}), "method_rows": len(run_rows),
        "reference_schema_valid": True, "human_quality_evaluated": False,
        "inference_calls": 0, "api_calls": 0, "model_downloads": 0,
        "source_hashes": source_hashes,
        "artifact_hashes": {key: sha(data) for key, data in artifacts.items()},
        "limitations": [
            ("DetectorReference/GroundTruth不支持图像哈希、版本、字段级确认日志及evaluation_scope；"
             "这些保留在manifest sidecar，不能粘贴到参考框JSON。"),
            "当前正式质量指标只接受完整且所有框确认的参考；部分确认继续未评测。",
            "P06未决人数仅在sidecar；ignore范围不能代表完整人物总数。",
            "旧run映射供识别来源；编辑保存须使用独立派生run或新参考版本，勿覆盖原实验。",
            "模型预测页引用旧实验内资源；搬移包时需保留来源目录或使用原绝对映射。",
        ],
    }
    artifacts["manifest.json"] = json_bytes(result)
    # Check the entire write set first: one conflict must not leave a partial new export.
    for name, data in artifacts.items():
        path = output / name
        if path.exists() and (not path.is_file() or path.read_bytes() != data):
            raise FileExistsError(f"Refuse to overwrite different existing output: {path}")
    if any(sha(Path(path).read_bytes()) != digest for path, digest in source_hashes.items()):
        raise ValueError("Source evidence changed while preparing the package")
    for name, data in artifacts.items():
        path = output / name
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as handle:
                handle.write(data)
        except FileExistsError:
            if path.read_bytes() != data:
                raise FileExistsError(f"Concurrent output conflict: {path}") from None
    if any(sha(Path(path).read_bytes()) != digest for path, digest in source_hashes.items()):
        raise ValueError("Source evidence changed during export; existing files were not rewritten")
    return result


def main():
    project = Path(__file__).resolve().parents[1]
    base = project / "data/vision_lab/detector_experiments"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=base / "iteration_20261013_01")
    parser.add_argument("--output", type=Path,
                        default=base / "preacceptance_20261013/confirmation_package")
    args = parser.parse_args()
    result = prepare_package(args.source, args.output)
    print(json.dumps({key: result[key] for key in [
        "output_directory", "sample_order", "all_ai_draft_objects", "pending_objects",
        "required_objects", "ignore_objects", "source_run_count", "method_rows",
    ]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
