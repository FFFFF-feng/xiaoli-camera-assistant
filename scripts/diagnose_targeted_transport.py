"""Offline diagnosis of preserved timeout/truncation requests, never sends a request."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "data/history/main-acceptance-20261014"
OUT = ROOT / "data/history/main-targeted-20261015"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    records = []
    for folder in [OLD / "live", OLD / "knowledge-comparison/without",
                   OLD / "knowledge-comparison/with"]:
        for calls_path in sorted(folder.glob("*-calls.json")):
            case = calls_path.name.removesuffix("-calls.json")
            if case not in {"P03", "D17"}:
                continue
            retrieval = folder / f"{case}-retrieval.json"
            hits = [hit for item in read(retrieval) for hit in item["hits"]] if retrieval.exists() else []
            for call in read(calls_path):
                if call["stage"] != "parameters":
                    continue
                prefix = f"{case}-parameters-attempt{call['attempt']}"
                request = read(folder / f"{prefix}-request.json")
                text = "\n".join(message.get("content", "") for message in request["messages"]
                                  if isinstance(message.get("content"), str))
                raw = folder / f"{prefix}.txt"
                records.append({
                    "case": case, "branch": str(folder.relative_to(OLD)), **call,
                    "request_text_chars": len(text),
                    "retrieval_text_chars": sum(len(hit["content"]) for hit in hits),
                    "retrieved_ids": [hit["document_id"] for hit in hits],
                    "max_output_tokens": request.get("max_tokens"),
                    "raw_chars": len(raw.read_text(encoding="utf-8")) if raw.exists() else None,
                    "finish_reason": None, "usage": None,
                    "metadata_limit": "Previous observer did not preserve provider usage/finish metadata; timeout has no response and rejected truncation has no saved body.",
                    "internal_output_fields_repeated_in_prompt": {
                        field: text.count('"' + field + '"') for field in (
                            "exposure_state", "validation_notes", "safety_notes", "reviewed_operations")},
                    "scene_context_occurrences": text.count("场景分析："),
                    "camera_context_occurrences": text.count("目标相机能力："),
                })
    report = {"api_calls": 0, "records": records,
              "known": ["P03 full-flow parameter request failed at 120.088 seconds.",
                        "P03 isolated with-knowledge parameter request rejected as truncated after 48.612 seconds.",
                        "The final schema asks for program-owned exposure_state, validation_notes, safety_notes and reviewed_operations; these are overwritten by code.",
                        "Production stages are serial and app renders final advice after pipeline.run completes."],
              "unknown": ["No previous usage or raw truncated body was preserved; cannot prove which field consumed output budget.",
                          "No server processing/queue time or tokens-per-second; root cause of timeout remains undetermined.",
                          "A single timeout and truncated branch do not prove retrieval length caused either failure."],
              "decision": "Add opt-in response observation; do not change timeout/output/retries/thinking/concurrency. No configuration experiment in this repair round."}
    (OUT / "timeout-truncation-diagnosis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"records": len(records), "api_calls": 0}))


if __name__ == "__main__":
    main()
