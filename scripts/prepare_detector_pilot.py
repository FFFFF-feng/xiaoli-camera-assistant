"""Prepare a separate, unscored pilot manifest using already downloaded images.

This command never invokes models, downloads images, copies historical evaluations,
or changes a historical manifest. Task text is authored below, not inferred from
filenames, titles, prior AI reviews, or evaluation checkpoints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

PILOT_ID = "detector_pilot10_v2"
# These are explicit experimental user tasks. They are not reference answers.
PILOT_TASKS = [
    (
        "contrast_10_v1",
        "P02",
        "开发",
        "逐一定位画面中可见的人物；没有指定唯一主角，请保留主角歧义。",
    ),
    (
        "complement_10_v1",
        "B02",
        "开发",
        "定位水杯整体和杯中可见区域，保留透明边缘；实体归属无法判定时说明未知。",
    ),
    (
        "diverse_20_v1",
        "D03",
        "开发",
        "定位金属器具的整体与可见部件，保留伸出画面的边缘；器具用途未知。",
    ),
    (
        "contrast_10_v1",
        "P06",
        "验证",
        "定位人物实例，同时保留人物与周围景物的尺度关系；没有指定唯一主角。",
    ),
    ("diverse_20_v1", "D07", "验证", "分别定位两只手、泥坯和陶轮可见区域，不用整个人框代替手部。"),
    (
        "contrast_10_v1",
        "P09",
        "验证",
        "定位可见的人物实例及反射中的人物；没有依据时不确定实体归属。",
    ),
    (
        "diverse_20_v1",
        "D13",
        "验证",
        "定位喷溅区域、可见水滴和礁石，保留上方边缘；不推断真实速度。",
    ),
    ("complement_10_v1", "B03", "验证", "定位彩铅整体排列和可见彩铅实例；没有指定唯一主角。"),
    (
        "interpretation_10_v1",
        "C03",
        "验证",
        "定位画面中的人物候选，并区分可判定的现场实体与描绘实体；无法判断时保留未知。",
    ),
    (
        "diverse_20_v1",
        "D16",
        "验证",
        "定位日食整体可见区域和边缘亮点；亮点物理身份未知，不推断物理机制。",
    ),
]

ATTRIBUTION_FIELDS = (
    "source_page",
    "source_page_revision",
    "author",
    "license",
    "license_url",
    "attribution_required",
    "attribution_text",
    "downloaded_on",
    "changes_to_downloaded_photo",
)


def prepare_pilot(project_root: Path, output: Path | None = None) -> dict:
    project_root = Path(project_root).resolve()
    test_sets = project_root / "data" / "vision_lab" / "test_sets"
    output = Path(output) if output else test_sets / PILOT_ID / "manifest.json"
    if output.exists():
        raise FileExistsError(f"拒绝覆盖现有独立实验清单: {output}")
    manifests = {}
    samples = []
    for dataset_id, sample_id, split, task in PILOT_TASKS:
        source_manifest = test_sets / dataset_id / "manifest.json"
        if dataset_id not in manifests:
            data = json.loads(source_manifest.read_text("utf-8-sig"))
            manifests[dataset_id] = {s["sample_id"]: s for s in data["samples"]}
        source = manifests[dataset_id][sample_id]
        image_path = (source_manifest.parent / source["file"]).resolve()
        if not image_path.is_relative_to(project_root) or not image_path.is_file():
            raise ValueError(f"图片必须是项目内现有文件: {sample_id}")
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        if source.get("sha256") and source["sha256"] != digest:
            raise ValueError(f"图片哈希与原清单不符: {sample_id}")
        samples.append(
            {
                "sample_id": sample_id,
                "image_project_relative": image_path.relative_to(project_root).as_posix(),
                "sha256": digest,
                "bytes": image_path.stat().st_size,
                "dataset_split": split,
                "task_prompt": task,
                "task_prompt_sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
                "task_source": "explicit_pilot_user_task_v2",
                "source_dataset_id": dataset_id,
                "source_manifest_project_relative": source_manifest.relative_to(
                    project_root
                ).as_posix(),
                "attribution": {k: source[k] for k in ATTRIBUTION_FIELDS if k in source},
                "reference": {"complete": False, "objects": [], "source": "pending_human"},
            }
        )
    manifest = {
        "schema_version": "detector-pilot/2",
        "dataset_id": PILOT_ID,
        "experiment_version": "detector_pilot10_v2",
        "count": len(samples),
        "development_count": 3,
        "validation_count": 7,
        "quality_experiment_started": False,
        "blind_test": False,
        "prior_exposure": "这些图片已用于四轮测试并被查看；仅为阈值留出，不称未接触盲测。",
        "inference_input_policy": "仅发送 prepare_image 的共同 JPEG、明确 task_prompt 和冻结词典；禁止读取 reference、attribution 或历史评测生成查询。",
        "annotation_policy": "人工参考待确认；本清单没有真值框，定位指标保持未评测。",
        "freeze_policy": "只在 3 张开发图调参；冻结词典、阈值、配对与 ignore 规则后再明确启动 7 张留出图。新设置需新实验版本。",
        "samples": samples,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f"{output.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = prepare_pilot(args.project, args.output)
    print(f"已准备 {result['dataset_id']}：3 开发 / 7 验证；未开始质量实验，人工参考待确认。")


if __name__ == "__main__":
    main()
