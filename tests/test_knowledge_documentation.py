import json
import re
from pathlib import Path

from camera_assistant.knowledge.models import KnowledgeRecord


def test_handoff_document_template_matches_current_schema() -> None:
    document = Path(__file__).resolve().parents[1] / "docs" / "knowledge-development.md"
    content = document.read_text(encoding="utf-8")
    fence = chr(96) * 3
    blocks = re.findall(fence + r"json\n(.*?)\n" + fence, content, flags=re.DOTALL)
    assert len(blocks) == 1
    record = KnowledgeRecord.model_validate(json.loads(blocks[0]))
    assert record.schema_version == 1
    assert record.source.retrieval_allowed is False
    assert "模板" in record.content
