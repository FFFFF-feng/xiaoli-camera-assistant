import json

import pytest
import test_real_pipeline as fixtures
from test_parameter_recovery import answer
from test_real_pipeline import (
    FakeCompositionAdvisor,
    FakeLocalizer,
    FakeVision,
    localization,
)

from camera_assistant.models import KnowledgeHit
from camera_assistant.pipeline import CameraAssistantPipeline
from camera_assistant.services import cloud
from camera_assistant.services.advisor import OpenAICompatibleRecommendationAdvisor

settings = fixtures.settings
image_content = fixtures.image_content
user_request = fixtures.user_request

PRINCIPLE = "重要高光可能因过曝而失去细节。"


class Retrieved:
    def search(self, *args, **kwargs):
        return [KnowledgeHit(document_id="technique/highlights@v2", title="高光原则",
            content=PRINCIPLE, source="教材", metadata={"version": "2", "body": PRINCIPLE,
                                                        "conditions": "{}"})]


@pytest.mark.parametrize("citation_version,accepted", [(2, True), (1, False)])
def test_pipeline_preserves_only_source_supported_independent_principles_after_numeric_review(
    settings, image_content, user_request, monkeypatch, citation_version, accepted,
):
    payloads = []
    candidate = answer(reasons=[PRINCIPLE, "f/4保证全景清晰"], knowledge_citations=[{
        "claim_path": "reasons.0", "claim": PRINCIPLE,
        "document_id": "technique/highlights@v2", "version": citation_version,
        "source_excerpt": PRINCIPLE,
    }])

    def content(config, body):
        payloads.append(body)
        return json.dumps(candidate, ensure_ascii=False)

    monkeypatch.setattr(cloud, "_request_content", content)
    pipeline = CameraAssistantPipeline(settings, vision_analyzer=FakeVision(),
        localizer=FakeLocalizer(localization()), composition_advisor=FakeCompositionAdvisor(),
        advisor=OpenAICompatibleRecommendationAdvisor(settings), retriever=Retrieved())
    result = pipeline.run(image_content, user_request)
    assert len(payloads) == 1
    assert result.recommendation.shutter_speed == "1/500s 或更快"
    assert "f/4保证全景清晰" not in result.recommendation.reasons
    assert bool(result.knowledge_citation_review.accepted) is accepted
    if accepted:
        assert PRINCIPLE in result.recommendation.reasons
        link = result.knowledge_citation_review.accepted[0].citation
        assert result.recommendation.reasons[int(link.claim_path.split(".")[-1])] == PRINCIPLE
    else:
        assert PRINCIPLE not in result.recommendation.reasons
        assert result.knowledge_citation_review.rejected
