from pathlib import Path

from camera_assistant.services.retriever import LocalKnowledgeRetriever


def test_night_query_returns_night_knowledge() -> None:
    root = Path(__file__).resolve().parents[1]
    retriever = LocalKnowledgeRetriever(root / "knowledge")

    hits = retriever.search("夜晚手持拍摄，弱光，高 ISO，安全快门", top_k=3)

    assert hits
    assert any("夜景" in hit.title for hit in hits)


def test_waterfall_query_returns_waterfall_knowledge() -> None:
    root = Path(__file__).resolve().parents[1]
    retriever = LocalKnowledgeRetriever(root / "knowledge")

    hits = retriever.search("瀑布 水流 拉丝 慢门 三脚架", top_k=2)

    assert hits[0].title == "瀑布与水流拉丝"

