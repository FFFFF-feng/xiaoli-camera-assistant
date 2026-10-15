from __future__ import annotations

import re
from collections.abc import Callable

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
from camera_assistant.services.advice_review import final_composition_review
from camera_assistant.services.advisor import (
    DemoRecommendationAdvisor,
    OpenAICompatibleRecommendationAdvisor,
    RecommendationAdvisor,
)
from camera_assistant.services.camera_knowledge import CameraKnowledgeBase
from camera_assistant.services.cloud import ModelServiceError, request_budget
from camera_assistant.services.composition import (
    CompositionAdvisor,
    DemoCompositionAdvisor,
    OpenAICompatibleCompositionAdvisor,
)
from camera_assistant.services.composition_citations import (
    finalize_composition_citations,
    prepare_composition_citations,
)
from camera_assistant.services.environment import normalize_scene_environment
from camera_assistant.services.image_analyzer import ImageAnalyzer
from camera_assistant.services.localization import GroundingDinoLocalizer
from camera_assistant.services.parameter_recovery import (
    assess_parameters,
    error_feedback,
    recoverable_error,
)
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

    def run(
        self,
        image_content: bytes,
        request: UserRequest,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> PipelineResult:
        def report(message: str) -> None:
            if on_progress is not None:
                on_progress(message)

        report("正在检查图片与拍摄设备…")
        inspection = self.image_analyzer.analyze(image_content)
        device_notes: list[str] = []
        if request.device_type == "phone":
            camera = self.phone_knowledge.resolve(request.phone_profile_id)
            phone_mode = request.phone_capture_mode
            if phone_mode not in camera.modes:
                phone_mode = "auto"
                device_notes.append("请求的手机模式尚未确认，按照片模式检索和提供指导。")
            lens_id = request.phone_lens_id
            if lens_id not in {lens.lens_id for lens in camera.lenses}:
                lens_id = "main"
                device_notes.append("请求的手机镜头未收录，按主摄核对；拍摄前请确认。")
            effective_request = request.model_copy(
                update={
                    "camera_format": "不清楚",
                    "camera_profile_id": "generic_unknown",
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
            camera = self.camera_knowledge.resolve(request.camera_profile_id, request.camera_format)
            effective_request = request.model_copy(update={"camera_format": camera.sensor_format})
        candidates = self.scene_knowledge.find_candidates(effective_request, inspection)
        report("正在识别画面中的主体和光线…")
        scene = self.vision_analyzer.analyze(inspection, effective_request, candidates)
        scene = self.scene_knowledge.normalize(scene, candidates)
        scene = normalize_scene_environment(scene, effective_request)
        if effective_request.subject_motion != "不确定":
            scene = scene.model_copy(update={"subject_motion": {
                "静止": "static", "缓慢": "slow", "快速": "fast",
            }[effective_request.subject_motion]})
        elif not self.settings.demo_mode:
            scene = scene.model_copy(update={
                "subject_motion": "unknown",
                "uncertainties": list(dict.fromkeys([*scene.uncertainties,
                    "用户未确认主体运动；单帧图像不能测得真实速度，也不能由模糊或拉丝外观确定原曝光参数。"])),
            })
        if not self.settings.demo_mode:
            # Photo appearance is not a measurement of the original controls.
            # Route this entire fact domain to EXIF/user settings instead of
            # trying to certify arbitrary causal prose from the vision model.
            scene = scene.model_copy(update={"recognition_evidence": [
                item for item in scene.recognition_evidence if not re.search(
                    r"快门|慢门|长曝|曝光|ISO|光圈|进光量|感光度", item, re.IGNORECASE,
                )
            ]})
        localization = None
        if self.localizer is not None and not self.settings.demo_mode:
            report("正在定位主体，首次运行可能较慢…")
            localization = self.localizer.localize(inspection, effective_request, scene)
        report("正在查阅适用的拍摄知识…")
        query = self._build_query(effective_request, scene)
        query += f" 设备 {camera.display_name} {request.device_type}"
        canonical_subject = next(
            (candidate.subject for candidate in candidates if candidate.profile_id == scene.scene_type),
            "main subject",
        )
        conditions = build_knowledge_conditions(
            effective_request, scene, camera, canonical_subject, localization,
            inspection=inspection,
        )
        query += " 器材 " + " ".join(str(conditions.get(key, "")) for key in (
            "camera_model", "lens_model", "app", "capture_mode", "shutter_type",
        ))
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
                report("正在生成构图建议…")
                composition = self.composition_advisor.recommend(
                    inspection, effective_request, scene, localization, composition_hits, camera
                )
            except (ValueError, KeyError, TypeError) as exc:
                composition = CompositionAdvice(
                    status="unavailable", proposals=[],
                    notes=[str(exc) if isinstance(exc, ModelServiceError)
                           else "构图模型本次未生成可校验的建议，请重新分析。"],
                )
        recommendation, recovery = self._parameter_stage(
            effective_request, scene, hits, camera, report,
            conditions=conditions,
        )
        if scene.environment_context.uncertainties:
            recommendation = recommendation.model_copy(update={
                "risks": list(dict.fromkeys([
                    *recommendation.risks, *scene.environment_context.uncertainties,
                ])),
            })
        composition = prepare_composition_citations(composition, composition_hits, conditions)
        composition = final_composition_review(
            composition, recommendation, effective_request, scene, camera,
        )
        composition = finalize_composition_citations(composition, composition_hits, conditions)
        if composition is not None and scene.environment_context.uncertainties:
            composition = composition.model_copy(update={
                "uncertainties": list(dict.fromkeys([
                    *composition.uncertainties, *scene.environment_context.uncertainties,
                ])),
                "proposals": [proposal.model_copy(update={
                    "conditions": list(dict.fromkeys([
                        *proposal.conditions, *scene.environment_context.uncertainties,
                    ])),
                }) for proposal in composition.proposals],
            })
        from camera_assistant.services.knowledge_citations import review_knowledge_citations

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
            localization=localization,
            composition=composition,
            composition_knowledge_hits=composition_hits,
            parameter_recovery=recovery,
            knowledge_citation_review=review_knowledge_citations(recommendation, hits, conditions),
        )

    def _parameter_stage(self, request, scene, hits, camera, report, *, conditions=None):
        from camera_assistant.recovery_models import ParameterRecovery
        from camera_assistant.services.knowledge_citations import review_knowledge_citations

        recommendation = None
        recovery = ParameterRecovery()
        feedback = ""
        correction_attempted = False
        pending_facts = {}
        correct = getattr(self.advisor, "correct_parameters", None)
        with request_budget(limit=2) as budget:
            for attempt in range(2):
                try:
                    report("正在纠正缺失的拍摄参数…" if attempt else "正在生成拍摄参数与操作建议…")
                    candidate = (correct(request, scene, hits, camera, feedback) if attempt
                                 else self.advisor.recommend(request, scene, hits, camera))
                    if pending_facts:
                        # An independent model omission may be repaired while actual
                        # equipment facts remain unknown in every final explanation.
                        candidate = candidate.model_copy(update=pending_facts)
                    report("正在校验拍摄建议…")
                    source_review = review_knowledge_citations(candidate, hits, conditions)
                    recommendation = self.validator.validate(candidate, request, scene, camera)
                    # Numeric/control review rebuilds explanations. Carry over only
                    # independently supported source principles, never old prose or
                    # an inference that a generic principle proves a concrete value.
                    source_links = {item.citation.model_dump_json(): item.citation
                                    for item in source_review.accepted if item.citation is not None}
                    reasons = list(recommendation.reasons)
                    citations = []
                    for citation in recommendation.knowledge_citations:
                        if hasattr(citation, "model_dump_json") and citation.model_dump_json() in source_links:
                            if citation.claim not in reasons:
                                reasons.append(citation.claim)
                            citation = citation.model_copy(update={
                                "claim_path": f"reasons.{reasons.index(citation.claim)}",
                            })
                        citations.append(citation)
                    recommendation = recommendation.model_copy(update={
                        "reasons": reasons, "knowledge_citations": citations,
                    })
                    recovery = assess_parameters(recommendation, request, camera, candidate)
                    feedback = "\n".join(recovery.issues)
                    pending_facts = {name: getattr(candidate, name) for name in recovery.fact_parameters}
                    retryable = bool(set(recovery.missing_parameters) - set(recovery.fact_parameters))
                except (ValueError, KeyError, TypeError) as exc:
                    retryable = recoverable_error(exc)
                    feedback = error_feedback(exc)
                    if recommendation is None:
                        recovery = ParameterRecovery(
                            issues=[feedback],
                            missing_parameters=[
                                "shooting_mode", "aperture", "shutter_speed", "iso",
                                "exposure_compensation", "focus_mode", "metering_mode",
                                "drive_mode", "white_balance",
                            ],
                            user_confirmations=["参数阶段未完成；请确认模式、ISO控制方式、当前镜头可用光圈及机身实际快门，现场测光后再拍摄。"],
                        )
                    else:
                        recovery.issues.append(feedback)
                    if not retryable and self.composition_advisor is None:
                        raise
                if (not retryable or attempt or not callable(correct) or budget.used >= budget.limit):
                    break
                correction_attempted = True
            recovery.correction_attempted = correction_attempted
            recovery.api_calls = budget.used
            recovery.format_failures = budget.format_failures
        if recommendation is None:
            recommendation = CameraRecommendation(
                shooting_mode="未生成", aperture="未生成", shutter_speed="未生成", iso="未生成",
                exposure_compensation="未生成", focus_mode="未生成", metering_mode="未生成",
                drive_mode="未生成", white_balance="未生成", reasons=[], adjustments=[],
                risks=[feedback if feedback and isinstance(self.advisor, OpenAICompatibleRecommendationAdvisor)
                       else "参数模型本次未返回可校验的设置，请重新分析。"], confidence=0,
            )
        return recommendation, recovery

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
            f"画面环境 {scene.environment_context.content_environment} "
            f"拍摄位置 {scene.environment_context.shooting_location} "
            f"环境关系 {scene.environment_context.relationship} "
            f"光线候选 {scene.lighting} 参考图亮度 {scene.brightness} "
            f"运动 {scene.subject_motion} 动态范围 {scene.dynamic_range} "
            f"手持 {request.handheld} 三脚架 {request.tripod} "
            f"效果 {' '.join(scene.desired_effects)} "
            f"检索词 {' '.join(scene.retrieval_terms)}"
        )
