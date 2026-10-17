"""Build a static, script-free HTML gallery from stored analysis results."""

from __future__ import annotations

import html
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .evidence import RunLayout, load_json

_PALETTE = ["#3f5b6b", "#8a6f4d", "#5c7a5a", "#7a5c6b", "#6b6b7a", "#8a5a4d"]


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _points(path: Iterable[Iterable[float]], bbox: list[float]) -> str:
    x1, y1, x2, y2 = (float(value) for value in bbox)
    return " ".join(
        f"{x1 + float(point[0]) * (x2 - x1):.5f},{y1 + float(point[1]) * (y2 - y1):.5f}"
        for point in path
        if isinstance(point, (list, tuple)) and len(point) >= 2
    )


def render_board_svg(storyboard: dict[str, Any] | None) -> str:
    """Render the stored line art with the even-odd rule, as the frontend does."""
    if not isinstance(storyboard, dict):
        return '<p class="missing">无保存的线绘板</p>'
    layers = storyboard.get("layers") or []
    parts = [
        (
            '<svg class="board" viewBox="0 0 1 1" preserveAspectRatio="xMidYMid meet" '
            'role="img" aria-label="离线回放线绘">'
        ),
        '<rect x="0" y="0" width="1" height="1" fill="#f6f2e9"/>',
    ]
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict):
            continue
        color = _PALETTE[index % len(_PALETTE)]
        bbox = layer.get("bbox") or [0, 0, 1, 1]
        outline = layer.get("outline")
        contour_sets = layer.get("contours") or []
        holes = layer.get("holes") or []
        paths: list[str] = []
        if (
            isinstance(outline, list)
            and outline
            and isinstance(outline[0], (list, tuple))
            and isinstance(outline[0][0], (int, float))
        ):
            paths.append(_points(outline, bbox))
        for contour in contour_sets:
            if isinstance(contour, list):
                paths.append(_points(contour, bbox))
        if paths:
            rings = " ".join(f"M {path} Z" for path in paths if path)
            hole_rings = " ".join(
                f"M {_points(hole, bbox)} Z" for hole in holes if isinstance(hole, list)
            )
            d = rings + (" " + hole_rings if hole_rings else "")
            parts.append(
                f'<path d="{_escape(d)}" fill="{color}" fill-opacity="0.72" '
                'fill-rule="evenodd" stroke="#243038" stroke-width="0.004"/>'
            )
        for detail in layer.get("details") or []:
            if isinstance(detail, list):
                parts.append(
                    f'<polyline points="{_escape(_points(detail, bbox))}" fill="none" '
                    f'stroke="{color}" stroke-width="0.0035" stroke-linecap="round"/>'
                )
    parts.append("</svg>")
    return "".join(parts)


def _recommendation_text(recommendation: dict[str, Any] | None) -> str:
    if not isinstance(recommendation, dict):
        return "<p class='missing'>无参数建议</p>"
    fields = [
        ("拍摄模式", recommendation.get("shooting_mode")),
        ("光圈", recommendation.get("aperture")),
        ("快门", recommendation.get("shutter_speed")),
        ("ISO", recommendation.get("iso")),
        ("曝光补偿", recommendation.get("exposure_compensation")),
        ("白平衡", recommendation.get("white_balance")),
    ]
    rows = "".join(
        f"<tr><th>{_escape(label)}</th><td>{_escape(value)}</td></tr>"
        for label, value in fields
    )
    reasons = "".join(f"<li>{_escape(item)}</li>" for item in recommendation.get("reasons") or [])
    risks = "".join(f"<li>{_escape(item)}</li>" for item in recommendation.get("risks") or [])
    return (
        f"<table class='kv'>{rows}</table>"
        f"<h4>理由</h4><ul>{reasons}</ul>"
        f"<h4>风险</h4><ul>{risks}</ul>"
    )


def _composition_text(composition: dict[str, Any] | None) -> str:
    if not isinstance(composition, dict):
        return "<p class='missing'>无构图建议</p>"
    blocks = [f"<p><b>状态：</b>{_escape(composition.get('status'))}</p>"]
    for proposal in composition.get("proposals") or []:
        if not isinstance(proposal, dict):
            continue
        blocks.append(f"<h4>{_escape(proposal.get('goal'))}</h4>")
        for label, key in (
            ("为什么", "reasons"),
            ("动作", "actions"),
            ("取舍", "tradeoffs"),
            ("限制", "limitations"),
        ):
            items = proposal.get(key) or []
            if items:
                blocks.append(
                    f"<p class='label'>{label}</p><ul>"
                    + "".join(f"<li>{_escape(item)}</li>" for item in items)
                    + "</ul>"
                )
    notes = composition.get("notes") or []
    if notes:
        blocks.append(
            "<p class='label'>说明</p><ul>"
            + "".join(f"<li>{_escape(item)}</li>" for item in notes)
            + "</ul>"
        )
    return "".join(blocks)


def build_gallery(layouts: Iterable[RunLayout], output_dir: Path) -> dict[str, Any]:
    """Write ``gallery.html`` plus copied originals; return a receipt."""
    output_dir.mkdir(parents=True, exist_ok=True)
    assets = output_dir / "assets"
    assets.mkdir(exist_ok=True)
    cards = []
    receipt_cases = []
    for layout in layouts:
        summary = load_json(layout.summary_path)
        result = load_json(layout.result_path) if layout.result_path.is_file() else {}
        manifest_path = layout.root.parent / "run_manifest.json"
        manifest = load_json(manifest_path) if manifest_path.is_file() else {}
        sample = next(
            (item for item in manifest.get("samples") or [] if str(item.get("id")) == layout.case_id),
            {},
        )
        photo = Path((sample.get("photos") or [""])[0]) if sample.get("photos") else None
        photo_name = ""
        if photo and photo.is_file():
            photo_name = f"{layout.run}-{layout.case_id}{photo.suffix or '.jpg'}"
            shutil.copyfile(photo, assets / photo_name)
        payload = result.get("result") or {}
        board = None
        composition = payload.get("composition") or {}
        proposals = composition.get("proposals") or []
        if proposals and isinstance(proposals[0], dict):
            board = proposals[0].get("storyboard")
        scene = payload.get("scene") or {}
        failure_codes = [
            item.get("code")
            for item in summary.get("diagnostics") or []
            if isinstance(item, dict) and item.get("status") == "failed"
        ]
        stage_rows = "".join(
            f"<tr><td>{_escape(item.get('stage'))}</td>"
            f"<td>{_escape(round(float(item.get('duration_seconds') or 0), 3))}</td></tr>"
            for item in summary.get("timings") or []
            if isinstance(item, dict)
        )
        cards.append(
            "<section class='card'>"
            f"<header><h2>{_escape(layout.case_id)} · {_escape(sample.get('title') or '')}</h2>"
            f"<span class='badge'>离线回放 · 未调用模型</span></header>"
            f"<p class='meta'>{_escape(layout.run)} · 原始墙钟 {_escape(summary.get('seconds'))} 秒 · "
            f"source {_escape(summary.get('source_fingerprint'))}</p>"
            f"<p class='intent'>用户意图：{_escape(sample.get('intent'))}</p>"
            + (f"<p class='failure'>失败码：{_escape(', '.join(str(code) for code in failure_codes))}</p>"
               if failure_codes else "")
            + "<div class='grid'>"
            + "<figure><figcaption>原图</figcaption>"
            + (f"<img src='assets/{_escape(photo_name)}' alt='原图'>" if photo_name else "<p class='missing'>原图缺失</p>")
            + "</figure>"
            + f"<figure><figcaption>实际推荐图（存档）</figcaption>{render_board_svg(board)}</figure>"
            + f"<figure><figcaption>场景</figcaption><p>{_escape(scene.get('scene_label'))}</p>"
            f"<p>{_escape(scene.get('subject'))}</p><p>{_escape(scene.get('lighting'))}</p></figure>"
            + "</div><div class='grid text'>"
            + f"<article><h3>拍摄参数</h3>{_recommendation_text(payload.get('recommendation'))}</article>"
            + f"<article><h3>构图建议</h3>{_composition_text(composition)}</article>"
            + f"<article><h3>计时</h3><table class='kv'>{stage_rows}</table></article>"
            + "</div></section>"
        )
        receipt_cases.append(
            {
                "case_id": layout.case_id,
                "run": layout.run,
                "photo": f"assets/{photo_name}" if photo_name else None,
                "failure_codes": failure_codes,
                "seconds": summary.get("seconds"),
            }
        )

    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>线绘修复 · 离线证据回放</title>
<style>
:root {{ color-scheme: light; }}
body {{ margin:0; padding:24px; background:#e9e4da; color:#1f2a30;
  font:15px/1.6 "Microsoft YaHei","Noto Sans SC",system-ui,sans-serif; }}
h1 {{ font-size:22px; margin:0 0 6px; }}
.notice {{ background:#fff4d6; border:1px solid #d8b45a; padding:10px 14px;
  border-radius:8px; margin:12px 0 24px; }}
.card {{ background:#fffdf8; border:1px solid #cfc7b8; border-radius:12px;
  padding:18px; margin:0 0 24px; }}
header {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; }}
header h2 {{ font-size:19px; margin:0; flex:1 1 auto; }}
.badge {{ background:#1f2a30; color:#fff; border-radius:999px; padding:2px 10px;
  font-size:12px; }}
.meta {{ color:#5d6670; font-size:13px; margin:4px 0; word-break:break-all; }}
.intent {{ margin:8px 0; }}
.failure {{ color:#9c2f2f; font-weight:600; }}
.grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }}
.grid.text {{ margin-top:14px; }}
figure {{ margin:0; }}
figcaption {{ font-size:13px; color:#5d6670; margin-bottom:4px; }}
img, svg.board {{ width:100%; height:auto; display:block; border-radius:8px;
  background:#f6f2e9; }}
table.kv {{ border-collapse:collapse; width:100%; font-size:14px; }}
table.kv th, table.kv td {{ border-bottom:1px solid #e2dbcd; padding:3px 6px;
  text-align:left; }}
h3 {{ font-size:15px; margin:0 0 6px; }}
h4 {{ font-size:14px; margin:10px 0 2px; }}
.label {{ font-weight:600; margin:8px 0 0; }}
ul {{ margin:2px 0 8px; padding-left:20px; }}
.missing {{ color:#9c2f2f; }}
@media (max-width: 760px) {{
  body {{ padding:12px; }}
  .grid {{ grid-template-columns:1fr; }}
  header h2 {{ flex-basis:100%; }}
}}
</style></head><body>
<h1>线绘修复 · 离线证据回放</h1>
<div class="notice">本页面是一次静态回放：只读取已保存的结果与原图，不包含脚本，
不会向任何分析或预演接口发送 POST，也不会产生模型调用计费。历史结果的源码版本早于
检查点，不能当作集成版本验收。</div>
{''.join(cards)}
</body></html>
"""
    (output_dir / "gallery.html").write_text(document, encoding="utf-8")
    return {
        "schema": "line-drawing-replay-gallery-v1",
        "kind": "stored_result_replay",
        "offline": True,
        "generated_model_requests": 0,
        "page": str(output_dir / "gallery.html"),
        "cases": receipt_cases,
        "contains_scripts": False,
    }
