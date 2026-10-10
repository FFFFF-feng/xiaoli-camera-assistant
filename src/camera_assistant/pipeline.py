from __future__ import annotations

from camera_assistant.config import PROJECT_ROOT, Settings
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.models import KnowledgeHit, PipelineResult, SceneAnalysis, UserRequest
from camera_assistant.services.advisor import (
    DemoRecommendationAdvisor,
    OpenAICompatibleRecommendationAdvisor,
    RecommendationAdvisor,
)
from camera_assistant.services.camera_knowledge import CameraKnowledgeBase
from camera_assistant.services.image_analyzer import ImageAnalyzer
from camera_assistant.services.retriever import LocalKnowledgeRetriever
from camera_assistant.services.scene_knowledge import SceneKnowledgeBase
from camera_assistant.services.validator import RecommendationValidator
from camera_assistant.services.vision import (
    DemoVisionAnalyzer,
    OpenAICompatibleVisionAnalyzer,
    VisionAnalyzer,
)


class CameraAssistantPipeline:
    def __init__(
        self,
        settings: Settings,
        image_analyzer: ImageAnalyzer | None = None,
        camera_knowledge: CameraKnowledgeBase | None = None,
        vision_analyzer: VisionAnalyzer | None = None,
        retriever: LocalKnowledgeRetriever | ManagedKnowledgeRetriever | None = None,
        scene_knowledge: SceneKnowledgeBase | None = None,
        advisor: RecommendationAdvisor | None = None,
        validator: RecommendationValidator | None = None,
    ) -> None:
        self.settings = settings
        self.image_analyzer = image_analyzer or ImageAnalyzer(settings.max_image_mb)
        self.camera_knowledge = camera_knowledge or CameraKnowledgeBase(
            settings.knowledge_dir / "cameras" / "camera_profiles.yaml"
        )
        if retriever is not None:
            self.retriever = retriever
        elif settings.knowledge_mode == "managed":
            self.retriever = ManagedKnowledgeRetriever(
                KnowledgeStore(settings.knowledge_db_path or PROJECT_ROOT / "data" / "knowledge.db")
            )
        else:
            self.retriever = LocalKnowledgeRetriever(settings.knowledge_dir)
        self.scene_knowledge = scene_knowledge or SceneKnowledgeBase(
            settings.knowledge_dir / "recognition" / "scene_profiles.yaml"
        )
        self.validator = validator or RecommendationValidator()

        if settings.cloud_ready:
            self.vision_analyzer = vision_analyzer or OpenAICompatibleVisionAnalyzer(settings)
            self.advisor = advisor or OpenAICompatibleRecommendationAdvisor(settings)
        else:
            self.vision_analyzer = vision_analyzer or DemoVisionAnalyzer()
            self.advisor = advisor or DemoRecommendationAdvisor()

    def run(self, image_content: bytes, request: UserRequest) -> PipelineResult:
        inspection = self.image_analyzer.analyze(image_content)
        camera = self.camera_knowledge.resolve(request.camera_profile_id, request.camera_format)
        effective_request = request.model_copy(update={"camera_format": camera.sensor_format})
        candidates = self.scene_knowledge.find_candidates(effective_request, inspection)
        scene = self.vision_analyzer.analyze(inspection, effective_request, candidates)
        scene = self.scene_knowledge.normalize(scene, candidates)
        query = self._build_query(effective_request, scene)
        if isinstance(self.retriever, ManagedKnowledgeRetriever):
            hits = self.retriever.search(
                query,
                top_k=4,
                libraries=["scene", "technique", "equipment"],
                conditions={
                    "scene": scene.scene_type,
                    "subject": scene.subject,
                    "motion": scene.subject_motion,
                    "camera_profile_id": camera.profile_id,
                    "camera_format": camera.sensor_format,
                    "handheld": effective_request.handheld,
                    "tripod": effective_request.tripod,
                },
            )
        else:
            hits = self.retriever.search(query, top_k=4)
        notes = self._knowledge_notes(hits)
        recommendation = self.advisor.recommend(effective_request, scene, hits, camera)
        recommendation = self.validator.validate(
            recommendation, effective_request, scene, camera
        )
        return PipelineResult(
            inspection=inspection,
            camera_profile=camera,
            scene=scene,
            recommendation=recommendation,
            knowledge_hits=hits,
            knowledge_mode=(
                "managed" if isinstance(self.retriever, ManagedKnowledgeRetriever) else "legacy"
            ),
            knowledge_notes=notes,
        )

    def _knowledge_notes(self, hits: list[KnowledgeHit]) -> list[str]:
        if isinstance(self.retriever, ManagedKnowledgeRetriever):
            if not hits:
                return [
                    (
                        "受管知识库尚无匹配的已发布资料；本次建议没有受管知识依据，"
                        "演示规则仍可运行，不能视为知识库准确性验证。"
                    )
                ]
            return ["仅使用已发布、允许检索且条件匹配的资料；相关度不代表准确率。"]
        return ["当前使用旧版演示资料目录，不经过受管知识库的审核与发布流程。"]

    @staticmethod
    def _build_query(request: UserRequest, scene: SceneAnalysis) -> str:
        return (
            f"{request.intent} 场景 {scene.scene_label} {scene.scene_type} 主体 {scene.subject} "
            f"环境 {scene.environment} 光线 {scene.lighting} 亮度 {scene.brightness} "
            f"运动 {scene.subject_motion} 动态范围 {scene.dynamic_range} "
            f"手持 {request.handheld} 三脚架 {request.tripod} "
            f"效果 {' '.join(scene.desired_effects)} "
            f"检索词 {' '.join(scene.retrieval_terms)}"
        )
