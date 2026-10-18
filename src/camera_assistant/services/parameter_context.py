"""Default-off parameter prompt candidate. Smaller input is not a latency result."""
import json


def compact_context(request, scene, camera, facts, knowledge_hits):
    """Preserve all fields, including null/false capability and uncertainty values.

    Only byte-identical knowledge records are shared. Original citation positions,
    document identities, content and provenance remain available after expansion.
    """
    unique, indices = [], []
    for hit in knowledge_hits:
        value = {"document_id": hit.document_id, "title": hit.title, "content": hit.content,
                 "source": hit.source, "metadata": hit.metadata}
        if value not in unique:
            unique.append(value)
        indices.append(unique.index(value))
    return {"version": 1, "user_request": request.model_dump(mode="json"),
            "scene": scene.model_dump(mode="json"), "camera": camera.model_dump(mode="json"),
            "photography_facts_and_constraints": facts.prompt(),
            "knowledge_records": unique, "knowledge_citation_order": indices}


def candidate_prompt(legacy_prompt, request, scene, camera, facts, knowledge_hits, schema):
    rules = legacy_prompt.split("\n用户请求：", 1)[0]
    context = compact_context(request, scene, camera, facts, knowledge_hits)
    evidence = []
    for index, record in enumerate(context['knowledge_records']):
        positions = ','.join(str(i+1) for i, ref in enumerate(context['knowledge_citation_order']) if ref == index)
        evidence.append(f"[资料 {positions}: {record['title']}]\n{record['content']}\n出处："
            + json.dumps({'document_id': record['document_id'], 'source': record['source'], 'metadata': record['metadata']},
                         ensure_ascii=False, separators=(',', ':')))
    # Keep the familiar blocks and all normative prose. Do not wrap/escape the
    # controlled fact text in an extra JSON string merely to call it compact.
    return (rules + "\n[PARAMETER_CONTEXT_CANDIDATE_V1]\n"
            + "用户请求：" + request.model_dump_json()
            + "\n场景分析：" + scene.model_dump_json()
            + "\n目标相机能力：" + camera.model_dump_json()
            + "\n共享摄影事实与约束：" + facts.prompt()
            + "\n检索资料：\n" + '\n\n'.join(evidence)
            + "\n\nJSON Schema：\n" + json.dumps(schema, ensure_ascii=False, separators=(",", ":")))
