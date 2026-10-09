from io import BytesIO
from pathlib import Path

from PIL import Image

from camera_assistant.config import Settings
from camera_assistant.models import UserRequest
from camera_assistant.pipeline import CameraAssistantPipeline


def test_demo_pipeline_runs_end_to_end() -> None:
    root = Path(__file__).resolve().parents[1]
    settings = Settings(
        demo_mode=True,
        api_key="",
        base_url="https://example.invalid/v1",
        vision_model="",
        text_model="",
        timeout_seconds=5,
        max_image_mb=15,
        knowledge_dir=root / "knowledge",
    )
    image_buffer = BytesIO()
    Image.new("RGB", (640, 480), color=(42, 48, 60)).save(image_buffer, format="JPEG")

    result = CameraAssistantPipeline(settings).run(
        image_buffer.getvalue(),
        UserRequest(
            intent="夜晚拍正在跑动的小狗，希望主体清晰",
            subject_motion="快速",
            camera_format="APS-C",
            camera_profile_id="canon_eos_r50",
            focal_length_mm=50,
            max_aperture=4.0,
        ),
    )

    assert result.scene.scene_type == "fast_pet"
    assert result.scene.scene_label == "快速宠物"
    assert result.scene.recognition_evidence
    assert result.recommendation.shutter_speed == "1/800s"
    assert result.recommendation.aperture.startswith("f/4")
    assert result.camera_profile.display_name == "Canon EOS R50"
    assert result.recommendation.shooting_mode == "Tv 快门优先"
    assert result.recommendation.focus_mode.startswith("Servo AF")
    assert result.knowledge_hits
