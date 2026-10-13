"""Export an immutable local evidence gallery and merged error ledger.

No model calls, record edits, accuracy calculation, or confirmation upgrades.
Usage:
    python scripts/export_detector_evidence.py EXPERIMENT_DIR
Existing galleries are preserved; later exports receive a timestamped directory.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote


def esc(value):
    return html.escape(str(value), quote=True)


def pretty(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)


def stable_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     default=str).encode("utf-8")).hexdigest()


def json_read(path, failures):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        failures.append({"error_id": "ENGINEERING-READ-" + stable_hash(str(path))[:16],
                         "source": "engineering", "confirmed": False,
                         "stage": "evidence_export", "title": "Evidence JSON could not be read",
                         "evidence": str(exc), "source_file": str(path)})
        return None


def href(path, output):
    return esc(quote(os.path.relpath(path, output).replace(os.sep, "/"), safe="/"))


def link(path, output, label=None):
    if path is None or not path.exists():
        return '<span class="muted">文件不存在/尚未保存</span>'
    return f'<a href="{href(path, output)}">{esc(label or path.name)}</a>'


def image_card(path, output, title):
    if not path.exists():
        return f'<figure><figcaption>{esc(title)}：未保存叠框</figcaption></figure>'
    return (f'<figure><a href="{href(path, output)}">'
            f'<img src="{href(path, output)}" loading="lazy" alt="{esc(title)}"></a>'
            f'<figcaption>{esc(title)} · {link(path, output)}</figcaption></figure>')


def error_records(value, context=None, pointer="$"):
    """Accept nested errors lists, root lists, and records from other reviewers."""
    inherited = dict(context or {})
    if isinstance(value, dict):
        for key in ("sample_id", "image_id", "version", "source", "annotation_source", "confirmed"):
            if key in value:
                inherited[key] = value[key]
        if "error_id" in value or ("stage" in value and "evidence" in value
                                    and ("method" in value or "title" in value)):
            yield value, inherited, pointer
            return
        for key, child in value.items():
            if key in ("errors", "error_entries", "error_ledger") and isinstance(child, list):
                for idx, item in enumerate(child):
                    if isinstance(item, dict):
                        yield item, inherited, f"{pointer}.{key}[{idx}]"
            elif isinstance(child, (dict, list)):
                yield from error_records(child, inherited, pointer + "." + key)
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from error_records(child, inherited, f"{pointer}[{idx}]")


def normalize_error(record, context, source_path, pointer):
    original = dict(record)
    source = str(record.get("source", record.get("annotation_source",
                 context.get("source", context.get("annotation_source", "unknown")))))
    normalized_source = "ai" if source.lower() in {"ai", "assistant", "ai_auxiliary"} else source
    declared_confirmed = record.get("confirmed", context.get("confirmed", False))
    normalized_confirmed = declared_confirmed is True and normalized_source != "ai"
    cause = record.get("cause", record.get("suspected_cause", record.get("reason", "")))
    evidence_status = cause.get("evidence_status", "") if isinstance(cause, dict) else record.get("cause_status", "")
    cause_statement = cause.get("statement", pretty(cause)) if isinstance(cause, dict) else cause
    original_id = record.get("error_id")
    derived_id = "DERIVED-" + stable_hash([str(source_path), pointer, original])[:20]
    row = {
        "error_id": str(original_id or derived_id),
        "original_error_id": original_id,
        "id_was_derived": not bool(original_id),
        "sample_id": record.get("sample_id", record.get("image_id", context.get("sample_id", context.get("image_id", "")))),
        "method": record.get("method", record.get("methods", "")),
        "version": record.get("version", context.get("version", "")),
        "stage": record.get("stage", record.get("tag", "")),
        "source": normalized_source,
        "confirmed": normalized_confirmed,
        "original_declared_confirmed": declared_confirmed,
        "confirmation_status": record.get("confirmation_status", "AI待确认" if normalized_source == "ai" else "保留来源声明；不是人工准确率"),
        "title": record.get("title", record.get("tag", "")),
        "severity": record.get("severity", ""),
        "model_quote": record.get("model_quote", record.get("model_conclusion", record.get("original_quote", ""))),
        "query": record.get("query", record.get("queries", "")),
        "bbox": record.get("bbox", record.get("model_bbox", "")),
        "evidence": record.get("evidence", record.get("visible_evidence", "")),
        "cause": cause_statement,
        "cause_evidence_status": evidence_status,
        "proposed_change": record.get("proposed_change", record.get("change", record.get("proposed_fix", ""))),
        "provenance": [{"file": str(source_path), "json_pointer": pointer}],
        "original_record": original,
    }
    if normalized_source == "ai" and declared_confirmed is True:
        row["normalization_note"] = "AI记录不具备人工确认资格；原声明保留，统一视图confirmed=false。"
    return row


def collect_errors(base, failures):
    sources = set(base.glob("error_ledger*.json"))
    sources.update(base.glob("run_export_failure*.json"))
    sources.update(base.glob("ledger_reconciliation*.json"))
    review_dir = base / "ai_reviews"
    if review_dir.exists():
        sources.update(review_dir.rglob("*.json"))
    outputs_dir = base / "outputs"
    if outputs_dir.exists():
        sources.update(outputs_dir.rglob("*export_failure*.json"))
        sources.update(outputs_dir.rglob("*ledger_reconciliation*.json"))
    sources = {p for p in sources if p.is_file() and p.name != "error_ledger.json"}
    merged = {}
    conflicts = []
    for path in sorted(sources):
        data = json_read(path, failures)
        if data is None:
            continue
        engineering_file = "export_failure" in path.name or "ledger_reconciliation" in path.name
        records = list(error_records(data, {"source": "engineering", "confirmed": False}
                                      if engineering_file else None))
        if not records and engineering_file:
            records = [({"error_id": "ENGINEERING-EVIDENCE-" + stable_hash([str(path), data])[:16],
                         "source": "engineering", "confirmed": False,
                         "stage": "run_export_failure" if "export_failure" in path.name else "ledger_reconciliation",
                         "title": path.stem, "evidence": data}, {}, "$")]
        for record, context, pointer in records:
            row = normalize_error(record, context, path.relative_to(base), pointer)
            key = row["error_id"]
            comparable = {k: v for k, v in row.items() if k != "provenance"}
            if key in merged:
                old = {k: v for k, v in merged[key].items() if k != "provenance"}
                if old == comparable:
                    merged[key]["provenance"].extend(row["provenance"])
                    continue
                variant = key + "--variant-" + stable_hash(comparable)[:12]
                conflicts.append({"error_id": key, "retained_variant_id": variant,
                                  "reason": "Same original ID has different source content; both retained."})
                row["error_id"] = variant
                key = variant
            merged[key] = row
    for failure in failures:
        row = normalize_error(failure, {}, Path(failure.get("source_file", "export")), "$")
        merged.setdefault(row["error_id"], row)
    return list(merged.values()), conflicts


def write_ledger(output, errors, conflicts):
    body = {
        "schema": "unified-evidence-error-ledger-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "official_human_accuracy": None,
        "official_human_quality_status": "未评测；本文件汇集错误证据，不计算准确率。",
        "policy": "保留原记录；AI confirmed=false；工程证据不作为照片人工真值。",
        "csv_text_policy": "CSV对可被表格程序当作公式的文本加字面量前缀；原文完整保留于JSON。",
        "id_conflicts": conflicts,
        "errors": errors,
    }
    (output / "error_ledger.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    columns = ["error_id", "original_error_id", "sample_id", "method", "version", "stage",
               "source", "confirmed", "original_declared_confirmed", "confirmation_status",
               "title", "severity", "model_quote", "query", "bbox", "evidence", "cause",
               "cause_evidence_status", "proposed_change", "provenance"]
    with (output / "error_ledger.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in errors:
            values = {k: pretty(record.get(k, "")) if isinstance(record.get(k), (dict, list))
                      else record.get(k, "") for k in columns}
            writer.writerow({k: "'" + value if isinstance(value, str)
                             and value.startswith(("=", "+", "-", "@", "\t", "\r"))
                             else value for k, value in values.items()})


def get_results(run):
    results = run.get("results", run.get("methods", []))
    if isinstance(results, dict):
        return [{"method": key, **value} for key, value in results.items()
                if isinstance(value, dict)]
    return [v for v in results if isinstance(v, dict)] if isinstance(results, list) else []


def run_html(base, output, version, sid, failures):
    folder = base / "outputs" / version / sid / "paired"
    run_path = folder / "run.json"
    if not run_path.exists():
        files = sorted((base / "outputs" / version / sid).rglob("*"))
        links = " · ".join(link(p, output) for p in files if p.is_file() and p.suffix in {".json", ".txt"})
        return f'<p>run.json未保存；完成、失败、未发送状态以原记录为准。</p><p>{links}</p>'
    run = json_read(run_path, failures)
    if not isinstance(run, dict):
        return f'<p>运行记录读取失败：{link(run_path, output)}</p>'
    snapshot = run.get("vlm") or {}
    cards = []
    results = {r.get("method"): r for r in get_results(run)}
    for method in ("A", "B1", "B2"):
        result = results.get(method, {})
        selection = result.get("selection") or {}
        detection = result.get("detection") or {}
        status = result.get("status", "未保存")
        cache = detection.get("cache_hit", snapshot.get("cache_hit", False) if method == "A" else False)
        cache_text = "缓存回放，非新实测" if cache else "来源见原记录"
        payload = {"queries": result.get("queries", {}), "association": selection,
                   "unsupported_targets": result.get("unsupported_targets", []),
                   "stages": result.get("stages", {})}
        review_overlay = folder / f"{method}_review_overlay.jpg"
        displayed_overlay = review_overlay if review_overlay.exists() else folder / f"{method}_overlay.jpg"
        indexed_candidates = [{"display_index": i, **obj} for i, obj in
                              enumerate(result.get("candidates") or [])]
        cards.append(f'<article><h4>{method} · {esc(status)}</h4>'
                     f'<p>{esc(cache_text)} · selection={esc(selection.get("status", "未保存"))}'
                     f' · candidates={len(result.get("candidates") or [])}</p>'
                     + image_card(displayed_overlay, output, method + " 复核叠框（短索引对应下方候选）")
                     + f'<p>{link(folder / (method + "_overlay.jpg"), output, "完整ID原叠框")} · '
                     + (link(folder / (method + "_candidates.csv"), output, "候选CSV")
                        if indexed_candidates else "无合法候选；原数组见JSON") + '</p>'
                     + f'<details><summary>短索引与原始候选ID/框</summary><pre>{esc(pretty(indexed_candidates))}</pre></details>'
                     + f'<details><summary>查询、关联、弃权及阶段</summary><pre>{esc(pretty(payload))}</pre></details></article>')
    raw_path = folder / "vlm_raw.txt"
    raw_answer = snapshot.get("raw_answer", "")
    if raw_path.exists():
        try:
            raw_answer = raw_path.read_text(encoding="utf-8-sig")
        except OSError:
            pass
    review_path = base / "ai_reviews" / version / f"{sid}.json"
    extra = f'<p>{link(run_path, output, "完整原始run.json")} · {link(raw_path, output, "原回答TXT")}'
    extra += " · " + link(review_path, output, "AI逐图复核（待确认）") + "</p>"
    pure_path = folder.parent / "pure" / "run.json"
    if pure_path.exists():
        extra += '<p>独立纯检测诊断：' + link(pure_path, output) + '</p>'
    if review_path.exists():
        review = json_read(review_path, failures)
        if isinstance(review, dict):
            selected = {k: review[k] for k in ("comparison_to_v0", "comparison_to_v1",
                         "required_coverage_ai", "levels_and_entities", "disposition") if k in review}
            extra += f'<details><summary>AI观察与版本变化（未人工确认）</summary><pre>{esc(pretty(selected))}</pre></details>'
    extra += f'<details><summary>未经修复的原始VLM回答 · {esc(snapshot.get("status", "未保存"))}</summary><pre>{esc(raw_answer)}</pre></details>'
    return extra + '<div class="methods">' + "".join(cards) + "</div>"


def choose_output(base, requested=None):
    output = requested.resolve() if requested is not None else base / "evidence_gallery"
    if output != base and base not in output.parents:
        raise ValueError("Output directory must stay inside the experiment directory.")
    if output == base:
        raise ValueError("Use a dedicated output directory, not the experiment root.")
    if output.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        output = output.with_name(output.name + "_" + stamp)
    output.mkdir(parents=True, exist_ok=False)
    return output


def export(base, requested=None, candidate="v1", rolled_back="v2"):
    base = base.resolve()
    if not base.is_dir():
        raise ValueError("Experiment directory does not exist.")
    output = choose_output(base, requested)
    failures = []
    inputs = base / "inputs"
    outputs = base / "outputs"
    sample_ids = {p.name for p in inputs.iterdir() if p.is_dir()} if inputs.exists() else set()
    versions = sorted([p.name for p in outputs.iterdir() if p.is_dir()],
                      key=lambda v: (int(v[1:]) if re.fullmatch(r"v\d+", v) else 999, v)) if outputs.exists() else []
    for version in versions:
        sample_ids.update(p.name for p in (outputs / version).iterdir() if p.is_dir())
    frozen_files = [base / name for name in ("manifest_original.json", "inputs.json", "plan.json",
                    "baseline_files.json", "request_ledger.json", "local_inference_ledger.jsonl",
                    "candidate_freeze.json", "candidate_decision.json", "round2_preregistration.json")]
    frozen_links = " · ".join(link(p, output) for p in frozen_files if p.exists())
    # Read frozen manifests for schema-independent display; do not recalculate their content.
    frozen_metadata = {p.name: json_read(p, failures) for p in frozen_files
                       if p.exists() and p.name in {"manifest_original.json", "inputs.json", "plan.json"}}
    sections = []
    for sid in sorted(sample_ids):
        input_dir = inputs / sid
        input_data = json_read(input_dir / "input.json", failures) if (input_dir / "input.json").exists() else {}
        task = input_data.get("task_prompt", "") if isinstance(input_data, dict) else ""
        split = input_data.get("dataset_split", "见冻结manifest") if isinstance(input_data, dict) else "未知"
        pictures = image_card(input_dir / "original.jpg", output, "冻结原图")
        pictures += image_card(input_dir / "sent.jpg", output, "实际发送JPEG")
        reference_path = base / "ai_references" / f"{sid}.json"
        reference = json_read(reference_path, failures) if reference_path.exists() else None
        previews = sorted((base / "ai_references" / "previews").glob(f"{sid}_*reference_page*.png"))
        reference_html = "".join(image_card(p, output, "AI参考叠框，待确认") for p in previews)
        if reference_path.exists():
            reference_html += "<p>" + link(reference_path, output, "冻结AI参考JSON与输入哈希") + "</p>"
            questions = reference.get("disputed_questions", reference.get("notes", "")) if isinstance(reference, dict) else ""
            reference_html += f'<details><summary>待确认的参考问题</summary><pre>{esc(pretty(questions))}</pre></details>'
        else:
            reference_html += '<p>本图没有冻结AI参考；照片判断仍需复核，人工指标未评测。</p>'
        vhtml = []
        for version in versions:
            if not (outputs / version / sid).exists():
                continue
            marker = " · 第二轮已回滚" if version == rolled_back else " · 冻结验证候选" if version == candidate else ""
            vhtml.append(f'<details open class="version"><summary>{esc(version + marker)}</summary>'
                         + run_html(base, output, version, sid, failures) + "</details>")
        sections.append(f'<section id="{esc(sid)}"><h2>{esc(sid)} · {esc(split)}</h2>'
                        f'<p>{esc(task)}</p><p class="notice">AI待确认；人工准确率、人工IoU/召回/完整任务质量未评测。</p>'
                        + '<div class="inputs">' + pictures + "</div>"
                        + '<details><summary>冻结参考预览与待确认问题</summary>' + reference_html + "</details>"
                        + "".join(vhtml) + "</section>")
    errors, conflicts = collect_errors(base, failures)
    write_ledger(output, errors, conflicts)
    review_links = " · ".join(link(p, output, str(p.relative_to(base))) for p in
                              sorted((base / "ai_reviews").rglob("*.json"))) if (base / "ai_reviews").exists() else ""
    diagnostic_links = " · ".join(link(p, output) for p in sorted(base.glob("ai_geometry_diagnostic*.json")))
    nav = " · ".join(f'<a href="#{esc(sid)}">{esc(sid)}</a>' for sid in sorted(sample_ids))
    css = """body{font:16px system-ui,sans-serif;margin:24px;max-width:1900px;background:#f5f6f8;color:#20242b}
a{color:#075aba}h1{font-size:25px}h2{margin-top:36px}h4{margin:4px 0}
.notice{background:#fff1ca;padding:10px;border-radius:6px}.muted{color:#68717c}
section{background:white;padding:18px;margin:18px 0;border:1px solid #dfe3e8;border-radius:10px}
.inputs,.methods{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.methods{grid-template-columns:repeat(3,minmax(0,1fr))}article{border:1px solid #e1e5ea;padding:12px;overflow:hidden}
figure{margin:10px 0}img{width:100%;height:auto;display:block}figcaption{font-size:13px;margin-top:5px}
summary{cursor:pointer;font-weight:650;padding:10px 0}.version{border-top:1px solid #dfe3e8;margin-top:15px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f0f2f5;padding:12px;font-size:13px;max-height:600px;overflow:auto}
@media(max-width:900px){.inputs,.methods{grid-template-columns:1fr}body{margin:10px}}"""
    page = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>检测定位实验证据 · AI待确认</title><style>{css}</style><body>
<h1>检测定位实验证据 · {esc(base.name)}</h1>
<p class="notice">AI待确认；官方人工准确率未评测。{esc(rolled_back)}第二轮范围改动已回滚；{esc(candidate)}作为格式契约工程候选进入冻结验证，不能由格式成功推断定位任务成功。</p>
<p>仅展示已保存记录，不发送模型请求，不修复原回答，不升级人工确认。每次导出为独立快照；缓存回放不计新实测。</p>
<nav>{nav}</nav><p>{frozen_links}</p>
<p>{link(output / "error_ledger.json", output, "统一错误台账JSON")} · {link(output / "error_ledger.csv", output, "统一错误台账CSV")} · 条目数={len(errors)} · ID冲突保留数={len(conflicts)}</p>
<details><summary>全部AI复核与独立几何辅助文件</summary><p>{review_links}</p><p>{diagnostic_links}</p></details>
<details><summary>冻结manifest与计划全文</summary><pre>{esc(pretty(frozen_metadata))}</pre></details>
{''.join(sections)}</body></html>"""
    (output / "index.html").write_text(page, encoding="utf-8")
    inventory = {"schema": "evidence-gallery-export-v1", "created_at": datetime.now(UTC).isoformat(),
                 "experiment_dir": str(base), "output_dir": str(output), "candidate": candidate,
                 "rolled_back": rolled_back, "sample_ids": sorted(sample_ids), "versions": versions,
                 "error_count": len(errors), "id_conflict_count": len(conflicts),
                 "read_failures": failures, "official_human_accuracy": None,
                 "original_records_modified": False}
    (output / "export_manifest.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, help="Must remain inside experiment; existing directory is preserved.")
    parser.add_argument("--candidate", default="v1")
    parser.add_argument("--rolled-back", default="v2")
    args = parser.parse_args()
    try:
        result = export(args.experiment_dir, args.output_dir, args.candidate, args.rolled_back)
    except (OSError, ValueError) as exc:
        parser.exit(1, "Evidence export failed: " + str(exc) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
