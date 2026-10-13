import hashlib
import json
from collections import defaultdict
from statistics import mean

from vision_lab_tool.models import Evaluation, ModelResult, Price, RunRecord, Usage, validate_box


def iou(a: list[float], b: list[float]) -> float:
    validate_box(a)
    validate_box(b)
    width = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    intersection = width * height
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return intersection / (area_a + area_b - intersection)


def estimate_cost(usage: Usage, price: Price) -> dict | None:
    if (
        usage.input_tokens is None
        or usage.output_tokens is None
        or price.input_per_million is None
        or price.output_per_million is None
        or not price.source_url
        or not price.checked_on
    ):
        return None
    limitations = [price.limitations]
    cached = usage.cached_tokens
    if cached is None:
        if price.cache_per_million is not None or not usage.input_includes_cache:
            return None
        cached = 0
        limitations.append("缓存明细未知：按全部输入原价计算上界，不表示缓存为零。")
    if cached and price.cache_per_million is None:
        return None
    writes = usage.cache_write_tokens
    if not usage.input_includes_cache and writes is None:
        return None
    if writes and price.cache_write_per_million is None:
        return None
    uncached = usage.input_tokens - cached if usage.input_includes_cache else usage.input_tokens
    if uncached < 0:
        return None
    output = usage.output_tokens
    if not usage.output_includes_reasoning:
        if usage.reasoning_tokens is None:
            return None
        output += usage.reasoning_tokens
    amount = (
        uncached * price.input_per_million
        + output * price.output_per_million
        + cached * (price.cache_per_million or 0)
        + (writes or 0) * (price.cache_write_per_million or 0)
    ) / 1_000_000
    return {
        "amount": amount,
        "currency": price.currency,
        "scope": limitations,
        "source_url": price.source_url,
        "checked_on": price.checked_on,
    }


def result_metrics(run: RunRecord, result: ModelResult) -> dict:
    obs = result.parsed
    if obs and run.mode == "advice":
        obs = obs["observation"]
    scene_match = None
    if run.reference.scene_annotated and obs:
        scene_match = {x["label"].strip() for x in obs["scene_labels"]} == {
            x.strip() for x in run.reference.scene_labels
        }
    evaluation = run.evaluations.get(result.result_id, Evaluation())
    refs = {o.object_id: o for o in run.reference.objects}
    preds = {o["object_id"]: o for o in obs["objects"]} if obs else {}
    values = []
    used_refs = set()
    for predicted_id, ref_id in evaluation.box_matches.items():
        pred, ref = preds.get(predicted_id), refs.get(ref_id)
        if pred and ref and pred["bbox"] is not None and ref.bbox is not None:
            if ref_id in used_refs:
                continue  # one-to-one matching only; UI prevents duplicate pairs
            used_refs.add(ref_id)
            values.append(iou(pred["bbox"], ref.bbox))
    return {"scene_match": scene_match, "ious": values, "reviewed": evaluation.reviewed}


def aggregate(runs: list[RunRecord], include_mock: bool = False) -> list[dict]:
    groups = defaultdict(list)
    for run in runs:
        for result in run.results:
            if result.config.protocol == "mock" and not include_mock:
                continue
            settings = result.config.model_dump(exclude={"config_id", "name", "price", "key_env"})
            settings["image_settings"] = {
                k: run.image.get(k) for k in ("longest_edge", "quality", "sent_format")
            }
            settings["actual_model"] = result.actual_model
            settings_hash = hashlib.sha256(
                json.dumps(settings, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            identity = (
                result.config.config_id,
                result.config.model_id,
                run.mode,
                run.experiment_version,
                run.dataset_split,
                run.prompt_sha256,
                settings_hash,
            )
            groups[identity].append((run, result))
    summaries = []
    for identity, pairs in groups.items():
        metrics = [result_metrics(run, result) for run, result in pairs]
        scenes = [m["scene_match"] for m in metrics if m["scene_match"] is not None]
        boxes = [value for m in metrics for value in m["ious"]]
        result = pairs[0][1]
        count = len(pairs)
        scores = {}
        for dimension in ("事实依据", "目标符合度", "可执行性", "器材可行性"):
            values = [
                run.evaluations.get(res.result_id, Evaluation()).scores.get(dimension)
                for run, res in pairs
            ]
            valid = [v for v in values if v is not None]
            scores[dimension] = {
                "mean": mean(valid) if valid else None,
                "evaluated": len(valid),
                "missing": count - len(valid),
            }
        summaries.append(
            {
                "config_id": identity[0],
                "model_id": identity[1],
                "model_name": result.config.name,
                "mode": identity[2],
                "experiment_version": identity[3],
                "dataset_split": identity[4],
                "prompt_sha256": identity[5],
                "request_settings_sha256": identity[6],
                "simulated": result.config.protocol == "mock",
                "samples": len({run.image["original_sha256"] for run, _ in pairs}),
                "runs": count,
                "human_evaluated": sum(m["reviewed"] for m in metrics),
                "human_missing": sum(not m["reviewed"] for m in metrics),
                "scene_evaluated": len(scenes),
                "scene_missing": count - len(scenes),
                "scene_exact_match": mean(scenes) if scenes else None,
                "box_pairs": len(boxes),
                "mean_iou": mean(boxes) if boxes else None,
                "format_pass_rate": mean(r.format_pass for _, r in pairs),
                "call_success_rate": mean(r.call_success for _, r in pairs),
                "mean_elapsed_seconds": mean(r.elapsed_seconds for _, r in pairs),
                "scores": scores,
            }
        )
    return summaries


def cost_totals(runs: list[RunRecord]) -> dict:
    result = {currency: {"estimated": 0.0, "known": 0, "unknown": 0} for currency in ("CNY", "USD")}
    for run in runs:
        for res in run.results:
            if res.config.protocol == "mock":
                continue
            total = result[res.config.price.currency]
            if res.cost is None:
                total["unknown"] += 1
            else:
                total["known"] += 1
                total["estimated"] += res.cost["amount"]
    return result
