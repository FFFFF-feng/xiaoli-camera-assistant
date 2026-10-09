from pathlib import Path

from camera_assistant.services.camera_knowledge import CameraKnowledgeBase


def camera_knowledge() -> CameraKnowledgeBase:
    root = Path(__file__).resolve().parents[1]
    return CameraKnowledgeBase(root / "knowledge" / "cameras" / "camera_profiles.yaml")


def test_camera_knowledge_resolves_specific_model() -> None:
    camera = camera_knowledge().resolve("canon_eos_r50", "不清楚")

    assert camera.display_name == "Canon EOS R50"
    assert camera.sensor_format == "APS-C"
    assert camera.crop_factor == 1.6
    assert camera.ibis_stops == 0
    assert camera.shutter_priority_name.startswith("Tv")


def test_camera_knowledge_falls_back_to_selected_format() -> None:
    camera = camera_knowledge().resolve("generic_unknown", "M4/3")

    assert camera.profile_id == "generic_m43"
    assert camera.crop_factor == 2.0
