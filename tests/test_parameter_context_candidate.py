import json

from test_photography_facts import camera
from test_validator import scene

from camera_assistant.models import KnowledgeHit, UserRequest
from camera_assistant.services.parameter_context import candidate_prompt, compact_context
from camera_assistant.services.photography_facts import build_photography_facts


def test_candidate_retains_all_facts_objects_unknowns_and_distinct_citation_sources():
    request = UserRequest(intent="保留暖色，拍奔跑主体", max_aperture=4, focal_length_mm=50)
    analysis = scene()
    profile = camera()
    facts = build_photography_facts(request, analysis, profile)
    hit = KnowledgeHit(document_id='one', title='知识', content='有效摄影约束', source='出处A', score=.8,
                       metadata={'source_url': 'https://example.invalid/reference'})
    other = hit.model_copy(update={'source': '出处B'})
    value = compact_context(request, analysis, profile, facts, [hit, hit, other])
    assert value['user_request'] == request.model_dump(mode='json')
    assert value['scene'] == analysis.model_dump(mode='json')
    assert value['camera'] == profile.model_dump(mode='json')
    assert value['photography_facts_and_constraints'] == facts.prompt()
    assert value['knowledge_citation_order'] == [0, 0, 1]
    assert [value['knowledge_records'][i]['source'] for i in value['knowledge_citation_order']] == ['出处A', '出处A', '出处B']
    assert '镜头防抖未确认' in value['photography_facts_and_constraints']
    assert value['user_request']['lighting_type'] is None  # Unknown remains explicit.


def test_schema_and_rules_remain_intact_not_merely_an_unstructured_short_prompt():
    request, analysis, profile = UserRequest(intent='保持倒影与峰线关联'), scene(), camera()
    facts = build_photography_facts(request, analysis, profile)
    schema = {'type': 'object', 'properties': {'mode': {'type': 'string', 'description': '模式控制边界'}}, 'required': ['mode']}
    prompt = candidate_prompt('完整曝光因果与模式约束\n用户请求：unused', request, analysis, profile, facts, [], schema)
    assert prompt.startswith('完整曝光因果与模式约束\n')
    assert json.loads(prompt.split('\nJSON Schema：\n')[1]) == schema
    assert facts.prompt() in prompt
    assert request.model_dump_json() in prompt and analysis.model_dump_json() in prompt
    assert profile.model_dump_json() in prompt


def test_product_candidate_is_off_without_explicit_constructor_opt_in():
    from camera_assistant.services.advisor import OpenAICompatibleRecommendationAdvisor
    assert OpenAICompatibleRecommendationAdvisor(None).compact_context is False
    assert OpenAICompatibleRecommendationAdvisor(None, compact_context=True).compact_context is True
