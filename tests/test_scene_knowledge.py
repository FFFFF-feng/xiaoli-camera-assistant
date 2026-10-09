from io import BytesIO
from pathlib import Path

from PIL import Image

from camera_assistant.models import UserRequest
from camera_assistant.services.image_analyzer import ImageAnalyzer
from camera_assistant.services.scene_knowledge import SceneKnowledgeBase


def make_inspection(color: tuple[int, int, int] = (80, 85, 90)):
    buffer = BytesIO()
    Image.new("RGB", (320, 240), color=color).save(buffer, format="JPEG")
    return ImageAnalyzer().analyze(buffer.getvalue())


def test_scene_knowledge_prefers_fast_pet() -> None:
    root = Path(__file__).resolve().parents[1]
    knowledge = SceneKnowledgeBase(root / "knowledge" / "recognition" / "scene_profiles.yaml")

    candidates = knowledge.find_candidates(
        UserRequest(intent="夜晚拍正在奔跑的小狗", subject_motion="快速"),
        make_inspection((35, 38, 42)),
    )

    assert candidates[0].profile_id == "fast_pet"
    assert candidates[0].evidence


def test_scene_knowledge_uses_tripod_night_profile() -> None:
    root = Path(__file__).resolve().parents[1]
    knowledge = SceneKnowledgeBase(root / "knowledge" / "recognition" / "scene_profiles.yaml")

    candidates = knowledge.find_candidates(
        UserRequest(
            intent="使用三脚架拍城市长曝光夜景",
            subject_motion="静止",
            handheld=False,
            tripod=True,
        ),
        make_inspection((20, 22, 25)),
    )

    assert candidates[0].profile_id == "tripod_night"
