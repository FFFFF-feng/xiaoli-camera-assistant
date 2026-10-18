"""Intercept the real advisor in memory; produce size/coverage data, never HTTP."""
from __future__ import annotations

import argparse
import copy
import json
import socket
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from camera_assistant.config import Settings
from camera_assistant.models import (
    CameraProfile,
    CameraRecommendation,
    KnowledgeHit,
    SceneAnalysis,
    UserRequest,
)
from camera_assistant.services import advisor
from camera_assistant.services.parameter_context import compact_context
from camera_assistant.services.photography_facts import photography_facts


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def inspect_case(name, request, scene, camera, hits, saved_recommendation, settings):
    payloads = []
    def fake_request_json(_settings, payload):
        payloads.append(copy.deepcopy(payload))
        return copy.deepcopy(saved_recommendation)
    with patch.object(advisor, 'request_json', fake_request_json):
        for enabled in (False, True):
            advisor.OpenAICompatibleRecommendationAdvisor(settings, compact_context=enabled).recommend(
                request, scene, hits, camera)
    assert len(payloads) == 2
    schema = CameraRecommendation.model_json_schema()
    facts = photography_facts(request, scene, camera)
    compact = compact_context(request, scene, camera, facts, hits)
    assert compact['user_request'] == request.model_dump(mode='json')
    assert compact['scene'] == scene.model_dump(mode='json')
    assert compact['camera'] == camera.model_dump(mode='json')
    assert compact['photography_facts_and_constraints'] == facts.prompt()
    assert [compact['knowledge_records'][i] for i in compact['knowledge_citation_order']] == [
        {'document_id': h.document_id, 'title': h.title, 'content': h.content, 'source': h.source, 'metadata': h.metadata}
        for h in hits]
    prompts = [p['messages'][0]['content'] for p in payloads]
    for prompt in prompts:
        assert json.loads(prompt.split('JSON Schema：\n')[-1]) == schema
    rows = []
    for payload, prompt in zip(payloads, prompts, strict=True):
        rows.append({'prompt_characters': len(prompt), 'prompt_utf8_bytes': len(prompt.encode('utf-8')),
                     'payload_characters': len(json.dumps(payload, ensure_ascii=False)),
                     'model': payload['model'], 'thinking_field_present': 'thinking' in payload,
                     'output_required_fields': schema['required']})
    counts = Counter(s for s in strings(compact) if len(s) >= 12)
    return {'case': name, 'input_scope': 'reconstructed_E2_manifest_request_plus_saved_scene_camera_knowledge',
        'not_recovered': ['exact runtime effective_request normalization', 'original provider-side tokenization'],
        'default': rows[0], 'candidate': rows[1],
        'candidate_minus_default_characters': rows[1]['prompt_characters']-rows[0]['prompt_characters'],
        'full_user_fields': len(compact['user_request']), 'full_scene_fields': len(compact['scene']),
        'full_camera_fields': len(compact['camera']), 'knowledge_input_count': len(hits),
        'unique_knowledge_records': len(compact['knowledge_records']),
        'repeated_long_strings': sum(n-1 for n in counts.values() if n > 1),
        'schema_characters_default': len(json.dumps(schema, ensure_ascii=False)),
        'schema_characters_minified': len(json.dumps(schema, ensure_ascii=False, separators=(',', ':'))),
        'coverage_checks': {'request': True, 'scene_including_objects_and_uncertainties': True, 'camera_capabilities': True,
            'local_photography_facts': True, 'knowledge_content_and_provenance': True, 'output_schema': True},
        'in_memory_interceptions': 2, 'cloud_requests': 0, 'latency_or_quality_equivalence_claimed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--e2-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    settings = Settings(demo_mode=False, api_key='offline-intercept-only', base_url='https://example.invalid',
        vision_model='offline-unchanged-model', text_model='offline-unchanged-model', timeout_seconds=120,
        max_image_mb=100, knowledge_dir=Path('knowledge'))
    rows = []
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('offline_only_no_network')):
        for case in ['06', '07', '02']:
            run = args.e2_root/f'e2-12bcccc-{case}'
            manifest = json.loads((run/'run_manifest.json').read_text(encoding='utf-8'))
            raw = json.loads((run/case/'result.json').read_text(encoding='utf-8'))
            value = raw.get('result', raw)
            request = UserRequest.model_validate(manifest['cases'][0]['request'])
            scene = SceneAnalysis.model_validate(value['scene'])
            camera = CameraProfile.model_validate(value['camera_profile'])
            hits = [KnowledgeHit.model_validate(hit) for hit in value['knowledge_hits']]
            rows.append(inspect_case(case, request, scene, camera, hits, value['recommendation'], settings))
            if case == '02':
                uncertain = request.model_copy(update={'subject_motion': '不确定', 'lighting_type': None})
                rows.append(inspect_case('counterexample_unknown_motion_light', uncertain, scene, camera,
                    [*hits, *hits], value['recommendation'], settings))
                synthetic = KnowledgeHit(document_id='offline_constraint_fixture', title='模式与器材约束反例',
                    content=photography_facts(request, scene, camera).prompt(), source='offline_synthetic_fixture', score=1.,
                    metadata={'source_location': 'self-contained constraint fixture, not E2 retrieval'})
                row = inspect_case('counterexample_knowledge_provenance', request, scene, camera,
                    [synthetic, synthetic], value['recommendation'], settings)
                row['input_scope'] = 'explicit_synthetic_duplicate_knowledge_counterexample_not_E2_retrieval'
                rows.append(row)
            if case == '07':
                tripod = request.model_copy(update={'handheld': False, 'tripod': True, 'max_aperture': 5.6})
                rows.append(inspect_case('counterexample_tripod_aperture', tripod, scene, camera,
                    hits, value['recommendation'], settings))
    report = {'kind': 'offline_parameter_payload_audit_v1', 'candidate_default_enabled': False,
        'method': 'actual OpenAICompatibleRecommendationAdvisor with in-memory fake request_json and socket denial',
        'cases': rows, 'cloud_requests': 0, 'real_first_content_latency_measured': False,
        'quality_equivalence_proven': False}
    with (args.out/'report.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'out': str(args.out), 'cases': len(rows), 'cloud_requests': 0,
        'character_deltas': {r['case']: r['candidate_minus_default_characters'] for r in rows}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
