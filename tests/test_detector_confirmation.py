"""Offline confirmation exports preserve evidence and never grant human status."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from vision_lab_tool.detector_models import (
    DetectorExperiment,
    DetectorReference,
    GroundTruth,
    MethodResult,
)


def generator():
    path = Path(__file__).resolve().parents[1] / "scripts/prepare_detector_confirmation.py"
    assert path.exists(), "Offline confirmation exporter is not implemented"
    spec = importlib.util.spec_from_file_location("confirmation_exporter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*")
            if path.is_file()}


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "frozen"
    refs = {
        "B02": [
            GroundTruth(gt_id="B02_cup_whole", label="cup", bbox=[.125, .1, .75, .75],
                        target_level="whole", annotation_source="ai"),
            GroundTruth(gt_id="B02_content_visible", label="visible cup content region",
                        bbox=[.2, .2, .6, .6], target_level="region",
                        parent_id="B02_cup_whole", annotation_source="ai"),
            GroundTruth(gt_id="B02_opening_visible", label="cup opening interior region",
                        bbox=[.2, .1, .6, .2], target_level="region", required=False,
                        parent_id="B02_cup_whole", annotation_source="ai"),
        ],
        "D03": [GroundTruth(gt_id="D03_rod", label="metal rod", bbox=[.2, 0, .5, .8],
                            target_level="part", truncated=True, annotation_source="ai")],
        "D07": [GroundTruth(gt_id="D07_wheel_visible", label="pottery wheel",
                            bbox=[.1, .2, .9, .8], target_level="region",
                            annotation_source="ai")],
        "C03": [GroundTruth(gt_id="C03_depicted_person", label="person",
                            bbox=[.2, .2, .6, .8], entity_kind="depiction",
                            annotation_source="ai")],
        "P06": [
            GroundTruth(gt_id="P06_person_uncertain_cluster", label="person",
                        bbox=[.2, .2, .4, .4], target_level="combination", ignore=True,
                        judgeable=False, ignore_reason="人数及边界待确认", annotation_source="ai"),
            GroundTruth(gt_id="P06_ledge_context", label="rock ledge", bbox=[0, .2, .8, .8],
                        target_level="region", required=False, out_of_scope=True,
                        annotation_source="ai"),
        ],
    }
    for index, (sample, objects) in enumerate(refs.items()):
        folder = root / "inputs" / sample
        folder.mkdir(parents=True)
        image = Image.new("RGB", (80, 60), (180, 180, 180))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG")
        original = buffer.getvalue()
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        corrected = buffer.getvalue()
        for filename, data in [("original.jpg", original), ("sent.jpg", original),
                               ("corrected.png", corrected)]:
            (folder / filename).write_bytes(data)
        metadata = {
            "sample_id": sample, "task_prompt": f"完整任务 {sample} <script>提醒</script>",
            "original_sha256": digest(original), "sent_sha256": digest(original),
            "corrected_sha256": digest(b"(80, 60)" + image.tobytes()), "original_size": [80, 60],
            "corrected_size": [80, 60], "sent_size": [80, 60],
        }
        (folder / "input.json").write_text(json.dumps(metadata), encoding="utf-8")
        reference = DetectorReference(objects=objects, annotation_policy="ai-draft-v1")
        draft = {
            "schema": "ai-reference-draft-v1", "sample_id": sample,
            "annotation_source": "ai", "confirmed": False, "complete": False,
            "task_prompt": metadata["task_prompt"], "input_hashes": {
                "original_sha256": digest(original), "sent_sha256": digest(original),
            }, "reference": reference.model_dump(mode="json"),
            "unresolved_instance_counts": ([{"gt_id": "P06_person_uncertain_cluster",
                                            "instance_count_min": 1, "instance_count_max": 3,
                                            "confirmed": False}] if sample == "P06" else []),
            "disputed_questions": ["请核对完整范围"],
        }
        (root / "ai_references").mkdir(exist_ok=True)
        (root / "ai_references" / f"{sample}.json").write_text(
            json.dumps(draft), encoding="utf-8")
        for version in ("v0", "v1"):
            run = DetectorExperiment(
                run_id=f"{index + 1:030x}" + version[-1] + "a", mode="localization",
                experiment_version=f"fixture:{version}:{sample}:paired",
                task_prompt=metadata["task_prompt"], task_prompt_sha256="fixture",
                image=metadata, configs=[], reference=reference,
                results=[MethodResult(method=method, status="empty") for method in ["A", "B1", "B2"]],
            )
            run.sample_file = run.run_id + ".png"
            outputs = root / "outputs" / version / sample / "paired"
            outputs.mkdir(parents=True)
            (outputs / "run.json").write_text(run.model_dump_json(indent=2), encoding="utf-8")
    return root


def test_export_preserves_full_reference_unknown_and_unresolved_counts(source, tmp_path):
    before = snapshot(source)
    output = tmp_path / "package"
    result = generator().prepare_package(source, output)
    assert snapshot(source) == before
    assert result["pending_objects"] == 8
    assert result["required_objects"] == 6
    assert result["sample_order"] == ["B02", "D03", "D07", "C03", "P06"]
    for sample in result["sample_order"]:
        exported = DetectorReference.model_validate_json(
            (output / sample / "reference.json").read_text("utf-8"))
        original = json.loads((source / "ai_references" / f"{sample}.json").read_text("utf-8"))
        assert exported.model_dump(mode="json") == original["reference"]
        assert not exported.complete
        assert all(obj.annotation_source == "ai" and not obj.confirmed for obj in exported.objects)
    p06 = json.loads((output / "P06" / "manifest.json").read_text("utf-8"))
    assert p06["unresolved_instance_counts"][0]["instance_count_max"] == 3
    assert p06["pending_objects"] == 2
    assert "<script>" not in (output / "index.html").read_text("utf-8")
    rows = json.loads((output / "source_runs.json").read_text("utf-8"))["rows"]
    assert len(rows) == 30
    assert rows[0]["sample_id"] == "B02" and rows[0]["version"] == "v1"
    assert rows[0]["method"] == "A" and rows[0]["recommended_initial"] is True
    assert all(row["source_run_sha256"] for row in rows)


def test_numbered_original_overlay_uses_corrected_orientation(source, tmp_path):
    folder = source / "inputs" / "B02"
    image = Image.new("RGB", (40, 80), "gray")
    exif = Image.Exif()
    exif[274] = 6
    original = io.BytesIO()
    image.save(original, "JPEG", exif=exif)
    (folder / "original.jpg").write_bytes(original.getvalue())
    corrected = io.BytesIO()
    Image.new("RGB", (80, 40), "gray").save(corrected, "PNG")
    (folder / "corrected.png").write_bytes(corrected.getvalue())
    metadata = json.loads((folder / "input.json").read_text("utf-8"))
    metadata.update(original_size=[40, 80], corrected_size=[80, 40],
                    original_sha256=digest(original.getvalue()),
                    corrected_sha256=digest(b"(80, 40)" + bytes([128, 128, 128]) * 3200))
    (folder / "input.json").write_text(json.dumps(metadata), encoding="utf-8")
    draft_path = source / "ai_references" / "B02.json"
    draft = json.loads(draft_path.read_text("utf-8"))
    draft["input_hashes"]["original_sha256"] = digest(original.getvalue())
    draft_path.write_text(json.dumps(draft), encoding="utf-8")
    # Run inputs must describe the same original image, without rewriting inferred boxes.
    for path in (source / "outputs").glob("*/B02/paired/run.json"):
        run = json.loads(path.read_text("utf-8"))
        run["image"] = metadata
        path.write_text(json.dumps(run), encoding="utf-8")
    output = tmp_path / "package"
    generator().prepare_package(source, output)
    assert (output / "B02" / "original.jpg").read_bytes() == original.getvalue()
    with Image.open(output / "B02" / "reference_original.png") as overlay:
        assert overlay.size == (80, 40)
        assert overlay.getpixel((10, 20)) != (128, 128, 128)
    with Image.open(output / "B02" / "reference_sent.png") as overlay:
        assert overlay.size == (80, 60)


def test_identical_regeneration_is_byte_stable(source, tmp_path):
    output = tmp_path / "package"
    module = generator()
    module.prepare_package(source, output)
    before = snapshot(output)
    module.prepare_package(source, output)
    assert snapshot(output) == before


def test_conflicting_output_is_refused_before_new_writes(source, tmp_path):
    output = tmp_path / "package"
    output.mkdir()
    (output / "index.html").write_text("older user work", encoding="utf-8")
    before = snapshot(output)
    with pytest.raises(FileExistsError, match="index.html"):
        generator().prepare_package(source, output)
    assert snapshot(output) == before


def test_hash_mismatch_does_not_create_package(source, tmp_path):
    (source / "inputs" / "D07" / "sent.jpg").write_bytes(b"wrong image")
    output = tmp_path / "package"
    with pytest.raises(ValueError, match="D07.*sent"):
        generator().prepare_package(source, output)
    assert not output.exists()


def test_corrected_pixel_digest_is_separate_from_png_file_digest(source, tmp_path):
    output = tmp_path / "package"
    generator().prepare_package(source, output)
    manifest = json.loads((output / "B02" / "manifest.json").read_text("utf-8"))
    assert manifest["corrected_sha256_basis"] == "str(RGB.size).encode() + RGB.tobytes()"
    png_hash = digest((output / "B02" / "corrected.png").read_bytes())
    assert manifest["corrected_png_file_sha256"] == png_hash
    assert png_hash != manifest["input"]["corrected_sha256"]


def test_different_source_run_task_cannot_be_presented_as_same_task(source, tmp_path):
    path = source / "outputs" / "v1" / "B02" / "paired" / "run.json"
    run = json.loads(path.read_text("utf-8"))
    run["task_prompt"] = "only the cup, omit its contents"
    path.write_text(json.dumps(run), encoding="utf-8")
    with pytest.raises(ValueError, match="B02.*task"):
        generator().prepare_package(source, tmp_path / "package")


def test_confirmed_source_is_refused_instead_of_resetting_human_fields(source, tmp_path):
    path = source / "ai_references" / "B02.json"
    draft = json.loads(path.read_text("utf-8"))
    draft["reference"]["objects"][0]["confirmed"] = True
    path.write_text(json.dumps(draft), encoding="utf-8")
    with pytest.raises(ValueError, match="B02.*AI"):
        generator().prepare_package(source, tmp_path / "package")
