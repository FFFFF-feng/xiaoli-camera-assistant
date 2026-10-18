"""Replay frozen observation metadata through current local pixels and layout.

This tool never contacts a model or service. It reuses historical estimates,
including wrong kinds/bboxes, and does not constitute new semantic acceptance.
Run with PYTHONPATH=src;scripts and an explicit, previously unused --out folder.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import html
import json
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from line_drawing_eval.gallery import render_board_svg
from line_drawing_eval.preflight import dirty_files, source_fingerprint

from camera_assistant.composition_models import CompositionIntent, CompositionProposal
from camera_assistant.config import Settings
from camera_assistant.services import segmentation_provider
from camera_assistant.services.composition_trace import observe_diagnostics
from camera_assistant.services.image_analyzer import ImageAnalyzer
from camera_assistant.services.layout_solver import solve_layout
from camera_assistant.services.pixel_contours import trace_observed_scene
from camera_assistant.services.segmentation_provider import get_provider, use_segmentation

ROOT = Path(__file__).resolve().parents[1]
CASE_IDS = ("02", "06", "07", "08")
LIMITS = [
    "复用历史冻结识别元数据及已有意图，未进行新视觉识别，不改kind/bbox；06历史building错类仍保留。",
    "仅验证当前本地像素提取与真实布局链路，未验证云端、参数建议、语义一致性或端到端耗时。",
    "mask_extracted、生成线绘或通过契约均不代表图像质量通过；须人工对照原照片。",
    "MobileSAM杯底丢行/杯沿误孔、狗耳眼球及连续结构可读性仍需逐图检查。",
    "超时为native阶段边界检查，不能中断在途本地推理；这里只记录实际耗时。",
]


class ReplayFailure(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _source(path):
    return {"path": str(path), "sha256": _sha(path) if path.is_file() else None}


def git_branch(root):
    return subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root,
        text=True, encoding="utf-8", errors="replace",
    ).strip()


def _settings(backend, weights, weights_sha256, timeout):
    # Build local-only options, without loading .env or credentials.
    if backend == "mobile_sam" and not (
        weights and weights.is_file() and re.fullmatch(r"[a-f0-9]{64}", weights_sha256 or "")
    ):
        raise ReplayFailure("mobile_sam_weights_required")
    if backend == "mobile_sam" and _sha(weights) != weights_sha256:
        raise ReplayFailure("weights_sha256_mismatch")
    return Settings(
        demo_mode=True, api_key="", base_url="https://example.invalid/v1",
        vision_model="", text_model="", timeout_seconds=120, max_image_mb=100,
        knowledge_dir=ROOT / "knowledge", segmentation_backend=backend,
        segmentation_weights_path=weights, segmentation_weights_sha256=weights_sha256 or "",
        segmentation_device="cpu", segmentation_timeout_seconds=timeout,
        segmentation_fallback=True, segmentation_evidence=True,
    )


def _composition(result):
    value = result.get("result", result) if isinstance(result, dict) else {}
    return value.get("composition") or {}


def _layout_inputs(result, scene):
    proposals = _composition(result).get("proposals") or []
    main_ids = {obj.object_id for obj in scene.objects if obj.role == "main"}
    for index, proposal in enumerate(proposals):
        if not isinstance(proposal, dict):
            continue
        try:
            intent = CompositionIntent.model_validate(proposal.get("composition_intent"))
        except (ValueError, TypeError):
            continue
        if intent.focus_object_id in main_ids:
            return intent, _proposal(proposal.get("goal")), "historical_composition_intent", index
    focus = next(obj for obj in scene.objects if obj.role == "main")
    intent = CompositionIntent(
        focus_object_id=focus.object_id, diagnosis="本地固定保留意图：仅检查冻结像素与布局。",
        placement="keep", vertical_placement="keep", subject_scale="keep", aspect="keep",
    )
    return intent, _proposal(None), "locally_fixed_keep_intent", None


def _proposal(goal):
    # A minimal carrier for the real solver, not a new model recommendation.
    return CompositionProposal(
        action_type="crop", goal=goal or "本地冻结元数据布局检查",
        actions=["仅比较本地线绘"], reasons=["冻结输入复用"], tradeoffs=["非新语义验收"],
        conditions=["须人工核对原图"], limitations=["未发起云端分析"],
    )


def _old_board(result):
    return next((proposal["storyboard"] for proposal in
                 _composition(result).get("proposals") or []
                 if isinstance(proposal, dict) and isinstance(proposal.get("storyboard"), dict)), None)


def _manifest_paths():
    root = segmentation_provider._EVIDENCE_ROOT
    return {path.resolve() for path in root.glob("*-manifest.json")} if root.is_dir() else set()


def _collect_evidence(before, target, image_sha256, processing):
    rows = []
    files = []
    destination = target / "provider"
    for path in sorted(_manifest_paths() - before):
        value = _load(path)
        if value.get("input_sha256") != image_sha256:
            continue
        associated = value.get("processing") or []
        if processing and [item.get("object_id") for item in associated] != [
            item.get("object_id") for item in processing
        ]:
            continue
        destination.mkdir(exist_ok=True)
        names = [path.name, value.get("contours"), value.get("drawing")]
        names.extend(item.get("file") for item in (value.get("masks") or {}).values())
        complete = True
        for name in names:
            if not isinstance(name, str) or Path(name).name != name:
                complete = False
                continue
            source = path.parent / name
            if not source.is_file() or source.is_symlink():
                complete = False
                continue
            shutil.copyfile(source, destination / name)
            files.append({"path": f"provider/{name}", "sha256": _sha(destination / name)})
        rows.append({
            "input_sha256": image_sha256, "local_manifest": f"provider/{path.name}",
            "source_manifest": str(path), "manifest_sha256": _sha(path),
            "processing": associated, "actual_backend": value.get("actual_backend"),
            "actual_backends": value.get("actual_backends"), "masks": value.get("masks") or {},
            "files_complete": complete, "contours_to_board": "scene.json -> board.json -> board.svg",
        })
    payload = {"records": rows, "files": files, "quality_passed": None,
               "limitation": "无raw mask时不能声称掩码质量已验收；有mask也须人工核对。"}
    _write(target / "provider-evidence.json", payload)
    return payload


def _standalone_svg(board):
    value = render_board_svg(board)
    if not isinstance(board, dict):
        return value
    aspect = {"landscape": 4/3, "portrait": .75, "square": 1}.get(board.get("aspect"), 1)
    height = 1000/aspect
    # The shared renderer uses normalized coordinates. Place them in the same
    # physical frame as TargetComposition; a square viewBox would distort them.
    content = value.split(">", 1)[1].rsplit("</svg>", 1)[0]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" class="board" '
            f'viewBox="0 0 1000 {height:.12g}" preserveAspectRatio="xMidYMid meet" '
            'role="img" aria-label="冻结输入离线线绘">'
            f'<g transform="scale(1000 {height:.12g})">{content}</g></svg>')


def _case(sample, evidence_root, target, settings):
    case_id = sample["id"]
    run = "live-run-2-diagnostic" if case_id == "07" else "live-run-1"
    source = evidence_root / run / case_id
    observation_path, result_path = source / "observation-replay.json", source / "result.json"
    historical_manifest = source.parent / "run_manifest.json"
    target.mkdir()
    started = time.monotonic()
    diagnostics, processing, before = [], [], _manifest_paths()
    record = {
        "case_id": case_id, "title": sample.get("title", case_id), "status": "started",
        "cloud_requests": 0, "quality_passed": None,
        "semantic_acceptance": "not_evaluated_frozen_metadata", "timings": {},
        "sources": {"observation": _source(observation_path), "historical_result": _source(result_path),
                    "historical_manifest": _source(historical_manifest)},
    }
    _write(target / "record.json", record)
    provider = get_provider(settings)
    try:
        photos = sample.get("photos") or []
        if len(photos) != 1:
            raise ReplayFailure("single_original_required")
        photo = Path(photos[0]).resolve()
        record["sources"]["original_photo"] = _source(photo)
        if _sha(photo) != sample.get("sha256"):
            raise ReplayFailure("original_sha256_mismatch")
        photo_name = "original" + photo.suffix.lower()
        shutil.copyfile(photo, target / photo_name)
        record["photo"] = photo_name
        preprocess_started = time.monotonic()
        inspection = ImageAnalyzer(max_image_mb=100).analyze(photo.read_bytes())
        record["timings"]["image_preprocessing"] = time.monotonic() - preprocess_started
        raw = base64.b64decode(inspection.model_image_data_url.split(",", 1)[1], validate=True)
        model_sha = hashlib.sha256(raw).hexdigest()
        record["model_image_sha256"] = model_sha
        observation = _load(observation_path)
        if model_sha != observation.get("model_image_sha256"):
            raise ReplayFailure("model_image_sha256_mismatch")
        metadata = observation.get("metadata")
        if not isinstance(metadata, dict):
            raise ReplayFailure("frozen_metadata_missing")
        _write(target / "frozen-metadata.json", metadata)
        record["frozen_metadata_sha256"] = _sha(target / "frozen-metadata.json")
        historical = _load(result_path) if result_path.is_file() else {}
        if historical_manifest.is_file():
            record["historical_version"] = _load(historical_manifest).get("source_fingerprint")
        old = _old_board(historical)
        _write(target / "historical-board.json", old)
        if old:
            (target / "historical-board.svg").write_text(_standalone_svg(old), encoding="utf-8")
        record["status"] = "hashes_verified"
        _write(target / "record.json", record)
        with use_segmentation(settings), observe_diagnostics(
            lambda diagnostic: diagnostics.append(diagnostic.model_dump(mode="json"))
        ):
            trace_started = time.monotonic()
            scene = trace_observed_scene(copy.deepcopy(metadata), inspection)
            record["timings"]["contours"] = time.monotonic() - trace_started
        processing = [row.model_dump(mode="json") for row in scene.processing]
        _write(target / "scene.json", scene.model_dump(mode="json"))
        record["processing"] = processing
        intent, proposal, origin, index = _layout_inputs(historical, scene)
        record.update({"intent_source": origin, "historical_intent_index": index,
                       "proposal_origin": "minimal_local_layout_carrier", "status": "contours_created"})
        _write(target / "record.json", record)
        _write(target / "intent.json", intent.model_dump(mode="json"))
        layout_started = time.monotonic()
        board, framing = solve_layout(intent, scene,
            inspection.metrics.width / inspection.metrics.height, proposal)
        record["timings"]["layout"] = time.monotonic() - layout_started
        _write(target / "board.json", board.model_dump(mode="json"))
        _write(target / "framing.json", framing.model_dump(mode="json"))
        (target / "board.svg").write_text(_standalone_svg(board.model_dump(mode="json")), encoding="utf-8")
        record["status"] = "output_created"
    except Exception as error:  # noqa: BLE001 - keep every attempt, never raw private errors
        code = getattr(error, "code", None)
        record.update({"status": "failed", "failure_code": code if isinstance(code, str)
                       and re.fullmatch(r"[a-z][a-z_0-9]{0,63}", code) else "offline_replay_failed",
                       "error_type": type(error).__name__})
    finally:
        evidence = _collect_evidence(before, target, record.get("model_image_sha256"), processing)
        record["mask_evidence_available"] = any(
            row["masks"] and row["files_complete"] for row in evidence["records"])
        record["provider_diagnostics"] = provider.diagnostics()
        record["provider_identity"] = provider.identity()
        record["timings"]["total"] = time.monotonic() - started
        _write(target / "diagnostics.json", diagnostics)
        _write(target / "timing.json", record["timings"])
        _write(target / "record.json", record)
    return record


def _gallery(report, out):
    cards = []
    for record in report["cases"]:
        case_id = record["case_id"]
        target = out / case_id
        image = f'<img src="{case_id}/{record["photo"]}" alt="原照片">' if record.get("photo") else "原图校验未完成"
        old = _standalone_svg(_load(target / "historical-board.json")) if (
            target / "historical-board.json").is_file() else "历史线绘缺失"
        board = _standalone_svg(_load(target / "board.json")) if (
            target / "board.json").is_file() else "当前离线提取失败"
        status = html.escape(record.get("failure_code", record["status"]))
        cards.append(f'<article><h2>{case_id} {html.escape(record["title"])}</h2>'
            f'<p>{status}；意图：{html.escape(record.get("intent_source", "未进入布局"))}</p>'
            f'<div class="columns"><section><h3>原照片</h3>{image}</section>'
            f'<section><h3>历史版本线绘</h3>{old}</section>'
            f'<section><h3>当前离线线绘</h3>{board}</section></div>'
            f'<p><a href="{case_id}/record.json">输入/版本/后端/耗时</a> · '
            f'<a href="{case_id}/provider-evidence.json">mask→轮廓→布局关联</a></p></article>')
    (out / "gallery.html").write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>集成后冻结输入离线对照</title><style>body{font:16px sans-serif;margin:24px;'
        'background:#faf8f2;color:#253239}article{border-top:1px solid #ccc;padding:18px 0}'
        '.columns{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}'
        'img,svg{width:100%;height:350px;object-fit:contain}section{min-width:0}'
        '@media(max-width:700px){.columns{grid-template-columns:1fr}}'
        '</style><h1>集成后冻结输入离线对照</h1><p>零云请求；复用历史冻结元数据，'
        '不是同版本完整云分析验收。历史与当前版本分别记录，质量状态均待人工评判。</p>'
        + "".join(f'<p>{html.escape(note)}</p>' for note in LIMITS)
        + "".join(cards) + '</html>', encoding="utf-8")


def run_replay(*, evidence_root, manifest_path, out, backend="grabcut", weights=None,
               weights_sha256="", timeout=120, cases=CASE_IDS):
    out, evidence_root, manifest_path = Path(out).resolve(), Path(evidence_root).resolve(), Path(manifest_path).resolve()
    if out.exists():
        raise FileExistsError(f"output already exists: {out}")
    if not cases or len(set(cases)) != len(cases) or set(cases) - set(CASE_IDS):
        raise ReplayFailure("invalid_case_ids")
    weights = Path(weights).resolve() if weights else None
    settings = _settings(backend, weights, weights_sha256, timeout)
    manifest = _load(manifest_path)
    samples = {str(sample.get("id")): sample for sample in manifest.get("samples") or []}
    if set(cases) - set(samples):
        raise ReplayFailure("manifest_case_missing")
    fingerprint = source_fingerprint(ROOT)
    out.mkdir(parents=True)
    report = {
        "schema": "integrated-segmentation-offline-v1", "cloud_requests": 0,
        "created_at": datetime.now().astimezone().isoformat(), "source_root": str(ROOT),
        "source_fingerprint": fingerprint, "branch": git_branch(ROOT),
        "dirty_files": dirty_files(ROOT), "manifest": _source(manifest_path),
        "evidence_root": str(evidence_root), "backend_requested": backend,
        "device": "cpu", "weights": _source(weights) if weights else None,
        "timeout_seconds": timeout, "quality_passed": None, "limitations": LIMITS,
        "case_count": len(cases), "output_count": 0, "cases": [],
    }
    _write(out / "report.json", report)
    try:
        for case_id in cases:
            row = _case(samples[case_id], evidence_root, out / case_id, settings)
            report["cases"].append(row)
            report["output_count"] += row["status"] == "output_created"
            _write(out / "report.json", report)
            _gallery(report, out)
    finally:
        get_provider(settings).close()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=Path(".tmp/line-drawing-repair-20261017"))
    parser.add_argument("--manifest", type=Path, default=Path(".tmp/line-drawing-eval-20261017/run_manifest.json"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--backend", choices=("grabcut", "mobile_sam"), default="grabcut")
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--weights-sha256", default="")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--cases", default=",".join(CASE_IDS))
    args = parser.parse_args(argv)
    report = run_replay(evidence_root=args.evidence_root, manifest_path=args.manifest, out=args.out,
        backend=args.backend, weights=args.weights, weights_sha256=args.weights_sha256,
        timeout=args.timeout, cases=tuple(args.cases.split(",")))
    print(json.dumps({"out": str(args.out.resolve()), "output_count": report["output_count"],
                      "case_count": report["case_count"], "cloud_requests": 0}, ensure_ascii=False))
    return 0 if report["output_count"] == report["case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
