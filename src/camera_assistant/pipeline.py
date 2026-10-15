from __future__ import annotations

from camera_assistant.composition_models import CompositionAdvice
from camera_assistant.config import PROJECT_ROOT, Settings
from camera_assistant.knowledge.context import build_knowledge_conditions
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.models import (
    CameraRecommendation,
    KnowledgeHit,
    PhoneProfile,
    PipelineResult,
    SceneAnalysis,
    UserRequest,
)
from camera_assistant.services.advisor import (
    DemoRecommendationAdvisor,
    OpenAICompatibleRecommendationAdvisor,
    RecommendationAdvisor,
)
from camera_assistant.services.camera_knowledge import CameraKnowledgeBase
from camera_assistant.services.cloud import ModelServiceError
from camera_assistant.services.composition import (
    CompositionAdvisor,
    DemoCompositionAdvisor,
    OpenAICompatibleCompositionAdvisor,
)
from camera_assistant.services.image_analyzer import ImageAnalyzer
from camera_assistant.services.lens_knowledge import LensKnowledgeBase
from camera_assistant.services.localization import GroundingDinoLocalizer
from camera_assistant.services.phone_knowledge import PhoneKnowledgeBase
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
        localizer: GroundingDinoLocalizer | None = None,
        composition_advisor: CompositionAdvisor | None = None,
        phone_knowledge: PhoneKnowledgeBase | None = None,
    ) -> None:
        self.settings = settings
        if not settings.demo_mode and not settings.cloud_ready:
            raise ValueError(
                "真实模式配置不完整：请填写模型与 API Key；GLM-DINO 可使用 ZHIPU_API_KEY "
                "或实验窗口保存的本机智谱密钥。"
            )
        self.image_analyzer = image_analyzer or ImageAnalyzer(settings.max_image_mb)
        self.phone_knowledge = phone_knowledge or PhoneKnowledgeBase(
            settings.knowledge_dir / "devices" / "phone_profiles.yaml"
        )
        self.camera_knowledge = camera_knowledge or CameraKnowledgeBase(
            settings.knowledge_dir / "cameras" / "camera_profiles.yaml"
        )
        self.lens_knowledge = LensKnowledgeBase(
            settings.knowledge_dir / "cameras" / "lens_profiles.yaml"
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
        self.localizer = localizer
        if settings.detector_enabled and settings.cloud_ready and self.localizer is None:
            self.localizer = GroundingDinoLocalizer(settings)
        self.composition_advisor = composition_advisor
        if settings.composition_enabled and self.composition_advisor is None:
            self.composition_advisor = (
                OpenAICompatibleCompositionAdvisor(settings) if settings.cloud_ready
                else DemoCompositionAdvisor()
            )

    def run(self, image_content: bytes, request: UserRequest) -> PipelineResult:
        inspection = self.image_analyzer.analyze(image_content)
        device_notes: list[str] = []
        equipment_settings = None
        if request.device_type == "phone":
            identifier = request.device_model_name or request.phone_profile_id
            camera = self.phone_knowledge.resolve(identifier)
            phone_mode = request.phone_capture_mode
            if phone_mode not in camera.modes:
                phone_mode = "auto"
                device_notes.append("请求的手机模式尚未确认，按照片模式检索和提供指导。")
            lens_id = request.phone_lens_id
            if lens_id not in {lens.lens_id for lens in camera.lenses}:
                lens_id = "main"
                device_notes.append("请求的手机镜头未收录，按主摄核对；拍摄前请确认。")
            selected_phone_lens = next(lens for lens in camera.lenses if lens.lens_id == lens_id)
            if phone_mode not in selected_phone_lens.modes:
                phone_mode = "auto"
                device_notes.append(
                    "该镜头的所选模式组合尚未核验，按照片模式提供指导；不代表该手机不支持此组合。"
                )
            effective_request = request.model_copy(
                update={
                    "camera_format": "不清楚",
                    "camera_profile_id": "generic_unknown",
                    "camera_lens_id": "",
                    "focal_length_mm": None,
                    "max_aperture": None,
                    "phone_profile_id": camera.profile_id,
                    "phone_capture_mode": phone_mode,
                    "phone_lens_id": lens_id,
                    "phone_pro_controls_confirmed": request.phone_pro_controls_confirmed
                    and phone_mode == "pro",
                }
            )
        else:
            identifier = request.device_model_name or request.camera_profile_id
            camera = self.camera_knowledge.resolve(identifier, request.camera_format)
            effective_request, equipment_settings, lens_notes = self.lens_knowledge.normalize(
                request, camera
            )
            device_notes.extend(lens_notes)
            if equipment_settings and equipment_settings.camera_lens:
                effective_request = effective_request.model_copy(update={
                    "target_lens_name": equipment_settings.camera_lens.display_name,
                })
            if camera.capability_level == "catalog":
                device_notes.append(
                    "已找到该相机的基础目录；硬件能力未核验，不继承其他机型的卡口、镜头、曝光范围或防抖。"
                )
            elif camera.capability_level == "basic":
                device_notes.append(
                    "本机型已录入画幅与原生卡口；ISO、快门和防抖边界尚未完整核验，建议不是硬件规格保证。"
                )
        if camera.profile_id.startswith("generic_"):
            supplied_name = request.device_model_name
            if not supplied_name and not identifier.startswith("generic_"):
                supplied_name = identifier.strip()[:120]
            if supplied_name:
                note = (
                    f"用户填写型号：{supplied_name}；能力资料未收录，采用通用指导，"
                    "不继承相近型号的模式、镜头或硬件上限。"
                )
                camera = camera.model_copy(
                    update={
                        "model": supplied_name,
                        "display_name": f"{supplied_name}（能力未收录）",
                        "notes": [*camera.notes, note],
                    }
                )
                device_notes.append(note)
            if request.device_type == "camera":
                device_notes.append("通用参数是试拍起点或演示约束，不是该型号已核实的硬件规格。")
        candidates = self.scene_knowledge.find_candidates(effective_request, inspection)
        scene = self.vision_analyzer.analyze(inspection, effective_request, candidates)
        scene = self.scene_knowledge.normalize(scene, candidates)
        if effective_request.subject_motion != "不确定":
            scene = scene.model_copy(update={"subject_motion": {
                "静止": "static", "缓慢": "slow", "快速": "fast",
            }[effective_request.subject_motion]})
        localization = None
        if self.localizer is not None and not self.settings.demo_mode:
            localization = self.localizer.localize(inspection, effective_request, scene)
        query = self._build_query(effective_request, scene)
        query += f" 设备 {camera.display_name} {request.device_type}"
        canonical_subject = next(
            (candidate.subject for candidate in candidates if candidate.profile_id == scene.scene_type),
            "main subject",
        )
        conditions = build_knowledge_conditions(
            effective_request, scene, camera, canonical_subject, localization,
        )
        query += " 器材 " + " ".join(str(conditions.get(key, "")) for key in (
            "camera_model", "lens_model", "app", "capture_mode", "shutter_type",
        ))
        if equipment_settings and equipment_settings.camera_lens:
            query += f" 镜头 {equipment_settings.camera_lens.display_name} 实际焦距 {effective_request.focal_length_mm}mm"
        if isinstance(self.retriever, ManagedKnowledgeRetriever):
            hits = self.retriever.search(
                query,
                top_k=4,
                libraries=["scene", "technique", "equipment"],
                conditions=conditions,
            )
        elif isinstance(camera, PhoneProfile):
            # 旧库没有设备适用性过滤，不能把相机手动参数当作手机依据。
            hits = []
        else:
            hits = self.retriever.search(query, top_k=4)
        notes = self._knowledge_notes(hits)
        notes.extend(device_notes)
        if isinstance(camera, PhoneProfile):
            notes.append(
                "手机使用独立型号能力目录和受控操作指导；当前不从检索正文推导手动曝光数值。"
            )
            if not isinstance(self.retriever, ManagedKnowledgeRetriever):
                notes[0] = "手机分支未检索旧相机Markdown库；启用managed并发布手机资料后才可检索。"
        composition_hits = []
        composition = None
        if self.composition_advisor is not None:
            composition_query = query + " 构图 留白 背景 主体位置 " + " ".join(scene.composition_clues)
            if isinstance(self.retriever, ManagedKnowledgeRetriever):
                composition_hits = self.retriever.search(
                    composition_query, top_k=4, libraries=["composition", "style", "case"],
                    conditions=conditions,
                )
            elif isinstance(camera, PhoneProfile):
                # Legacy cards do not carry phone applicability conditions.
                composition_hits = []
            else:
                # Legacy exposure cards must not be presented as a composition knowledge base.
                composition_hits = LocalKnowledgeRetriever(
                    self.settings.knowledge_dir / "composition"
                ).search(composition_query, top_k=4)
            try:
                composition = self.composition_advisor.recommend(
                    inspection, effective_request, scene, localization, composition_hits, camera
                )
            except (ValueError, KeyError, TypeError) as exc:
                composition = CompositionAdvice(
                    status="unavailable", proposals=[],
                    notes=[str(exc) if isinstance(exc, ModelServiceError)
                           else "构图模型本次未生成可校验的建议，请重新分析。"],
                )
        try:
            recommendation = self.advisor.recommend(effective_request, scene, hits, camera)
            recommendation = self.validator.validate(
                recommendation, effective_request, scene, camera
            )
        except (ValueError, KeyError, TypeError) as exc:
            if self.composition_advisor is None:
                raise
            # Preserve successful composition when the separate parameter stage fails.
            recommendation = CameraRecommendation(
                shooting_mode="未生成", aperture="未生成", shutter_speed="未生成", iso="未生成",
                exposure_compensation="未生成", focus_mode="未生成", metering_mode="未生成",
                drive_mode="未生成", white_balance="未生成", reasons=[], adjustments=[],
                risks=[str(exc) if isinstance(exc, ModelServiceError)
                       else "参数模型本次未返回可校验的设置，请重新分析。"], confidence=0,
            )
        recommendation.validation_notes = list(
            dict.fromkeys([*recommendation.validation_notes, *device_notes])
        )
        return PipelineResult(
            inspection=inspection,
            camera_profile=camera,
            equipment_settings=equipment_settings,
            scene=scene,
            recommendation=recommendation,
            knowledge_hits=hits,
            knowledge_mode=(
                "managed" if isinstance(self.retriever, ManagedKnowledgeRetriever) else "legacy"
            ),
            knowledge_notes=notes,
            localization=localization,
            composition=composition,
            composition_knowledge_hits=composition_hits,
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
