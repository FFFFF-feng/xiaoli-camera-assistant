import hashlib
from datetime import UTC, datetime

from vision_lab_tool.adapters import invoke
from vision_lab_tool.evaluation import estimate_cost
from vision_lab_tool.images import PreparedImage
from vision_lab_tool.models import ModelConfig, RunRecord
from vision_lab_tool.prompts import build_prompt
from vision_lab_tool.security import scrub


def run_comparison(
    configs: list[ModelConfig],
    image: PreparedImage,
    mode: str,
    template: str,
    context: dict,
    experiment_version: str,
    dataset_split: str,
    prompt_version: str,
    keys: dict | None = None,
    include_exif: bool = False,
    transport=None,
) -> RunRecord:
    if not 2 <= len(configs) <= 4:
        raise ValueError("每次请选择 2～4 个配置")
    if len({c.config_id for c in configs}) != len(configs):
        raise ValueError("比较配置 ID 必须独立")
    if mode not in {"recognition", "advice"}:
        raise ValueError("未知实验模式")
    keys = keys or {}
    include_exif = include_exif and mode == "advice"
    prompt = build_prompt(mode, template, {**context, "exif": image.exif}, include_exif)
    results = []
    for config in configs:
        result = invoke(
            config, prompt, image.data_url, mode, keys.get(config.config_id, ""), transport
        )
        if config.protocol != "mock":
            result.cost = estimate_cost(result.usage, config.price)
        results.append(result)
    # Also redact a service echoing the bare image base64, not just the data URL.
    secrets = [*keys.values(), image.data_url, image.data_url.partition(",")[2]]
    safe_prompt = scrub(prompt, secrets)
    allowed_context = (
        {k: context.get(k, "") for k in ("goal", "equipment", "reference")}
        if mode == "advice"
        else {}
    )
    if include_exif:
        allowed_context["original_capture_exif_only"] = image.exif
    return RunRecord.model_validate(
        scrub(
            RunRecord(
                created_at=datetime.now(UTC).isoformat(),
                mode=mode,
                experiment_version=experiment_version,
                dataset_split=dataset_split,
                image=image.metadata(),
                prompt=safe_prompt,
                prompt_version=prompt_version,
                prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                context={
                    **allowed_context,
                    "include_exif": include_exif,
                    "input_difference_note": "同一发送 JPEG；厂商内部缩放不可控制；detail 按配置记录。",
                },
                results=results,
            ).model_dump(mode="json"),
            secrets,
        )
    )
