"""受管检索回归测试；所有记录均为合成测试数据，不代表摄影知识。"""

from pathlib import Path
from typing import Any

import pytest

from camera_assistant.knowledge.models import KnowledgeRecord, Revision, SourceInfo
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeError, KnowledgeStore

LIBRARIES = ("scene", "composition", "style", "technique", "equipment", "case")


@pytest.fixture
def store(tmp_path: Path) -> KnowledgeStore:
    return KnowledgeStore(tmp_path / "test-knowledge.sqlite3")


@pytest.fixture
def retriever(store: KnowledgeStore) -> ManagedKnowledgeRetriever:
    return ManagedKnowledgeRetriever(store)


def make_record(knowledge_id: str = "test-record", **overrides: Any) -> KnowledgeRecord:
    data: dict[str, Any] = {
        "knowledge_id": knowledge_id,
        "library_id": "composition",
        "title": "测试数据：主体留白",
        "kind": "guideline",
        "content": "测试数据：主体留白与构图检索标记，不作为真实拍摄建议。",
        "source": {
            "name": "合成测试资料",
            "url": "https://example.com/test-data",
            "location": "测试章节 1",
            "license": "测试数据，无真实知识内容",
            "retrieval_allowed": True,
        },
        "author": "测试作者",
    }
    data.update(overrides)
    return KnowledgeRecord.model_validate(data)


def publish(store: KnowledgeStore, record: KnowledgeRecord) -> Revision:
    store.save_draft(record)
    store.submit(record.knowledge_id, record.version)
    store.approve(record.knowledge_id, reviewer="测试审核员", version=record.version)
    return store.publish(record.knowledge_id, record.version)


def test_empty_store_has_no_text_or_structured_results(
    retriever: ManagedKnowledgeRetriever,
) -> None:
    assert retriever.search("主体留白") == []
    assert retriever.query_structured("equipment") == []


@pytest.mark.parametrize("status", ["draft", "pending_review", "approved", "retired"])
def test_nonpublished_records_are_not_retrievable(
    store: KnowledgeStore, retriever: ManagedKnowledgeRetriever, status: str
) -> None:
    record = make_record(payload={"test_marker": "测试数据"})
    store.save_draft(record)
    if status != "draft":
        store.submit(record.knowledge_id)
    if status in {"approved", "retired"}:
        store.approve(record.knowledge_id, reviewer="测试审核员")
    if status == "retired":
        store.publish(record.knowledge_id)
        store.retire(record.knowledge_id)

    assert retriever.search("主体留白") == []
    assert retriever.query_structured("composition") == []


@pytest.mark.parametrize("restricted", ["evaluation", "permission"])
def test_evaluation_and_unpermitted_records_cannot_enter_retrieval(
    store: KnowledgeStore, retriever: ManagedKnowledgeRetriever, restricted: str
) -> None:
    record = make_record()
    if restricted == "evaluation":
        record.dataset_split = "evaluation"
    else:
        record.source.retrieval_allowed = False
    store.save_draft(record)
    store.submit(record.knowledge_id)
    store.approve(record.knowledge_id, reviewer="测试审核员")

    with pytest.raises(KnowledgeError):
        store.publish(record.knowledge_id)

    assert retriever.search("主体留白") == []
    assert retriever.query_structured("composition") == []


def test_retrieval_boundary_rechecks_status_split_and_permission(
    store: KnowledgeStore,
) -> None:
    revision = publish(store, make_record())
    evaluation = revision.model_copy(
        update={"record": make_record("test-evaluation", dataset_split="evaluation")}
    )
    unpermitted = revision.model_copy(
        update={
            "record": make_record(
                "test-unpermitted",
                source=SourceInfo(name="合成测试资料", retrieval_allowed=False),
            )
        }
    )
    retired = revision.model_copy(update={"status": "retired"})

    class FutureStore:
        """模拟未来存储实现意外返回了不合格修订，检索层仍需阻止。"""

        def list_revisions(self, status: str) -> list[Revision]:
            assert status == "published"
            return [revision, evaluation, unpermitted, retired]

    guarded = ManagedKnowledgeRetriever(FutureStore())  # type: ignore[arg-type]
    assert [hit.metadata["knowledge_id"] for hit in guarded.search("主体留白")] == [
        "test-record"
    ]
    assert [item.record.knowledge_id for item in guarded.query_structured("composition")] == [
        "test-record"
    ]


def test_chinese_search_ranks_related_content_above_unrelated_content(
    store: KnowledgeStore, retriever: ManagedKnowledgeRetriever
) -> None:
    publish(store, make_record("test-related"))
    publish(
        store,
        make_record(
            "test-unrelated", title="测试数据：快门", content="测试数据：快门、曝光和器材。"
        ),
    )

    hits = retriever.search("主体留白", top_k=2)

    assert hits
    assert hits[0].metadata["knowledge_id"] == "test-related"
    assert all(hit.score > 0 for hit in hits)


@pytest.mark.parametrize("library_id", LIBRARIES)
def test_each_of_six_libraries_can_be_filtered(
    store: KnowledgeStore, retriever: ManagedKnowledgeRetriever, library_id: str
) -> None:
    for name in LIBRARIES:
        publish(store, make_record(f"test-{name}", library_id=name))

    hits = retriever.search("检索标记", libraries=[library_id])

    assert len(hits) == 1
    assert hits[0].metadata["library_id"] == library_id
    assert len(retriever.search("检索标记", top_k=6)) == 6
    assert retriever.search("检索标记", libraries=[]) == []


def test_multiple_library_filter_excludes_other_libraries(
    store: KnowledgeStore, retriever: ManagedKnowledgeRetriever
) -> None:
    for name in LIBRARIES:
        publish(store, make_record(f"test-{name}", library_id=name))

    hits = retriever.search("检索标记", libraries=["composition", "style"])

    assert {hit.metadata["library_id"] for hit in hits} == {"composition", "style"}


@pytest.mark.parametrize("context", [None, {}, {"scene_type": "portrait"}])
def test_declared_conditions_require_all_context_fields(
    store: KnowledgeStore,
    retriever: ManagedKnowledgeRetriever,
    context: dict[str, Any] | None,
) -> None:
    publish(
        store,
        make_record(conditions={"scene_type": "portrait", "subject_motion": "static"}),
    )

    assert retriever.search("主体留白", conditions=context) == []


@pytest.mark.parametrize("motion", ["static", "slow"])
def test_condition_lists_have_or_semantics(
    store: KnowledgeStore, retriever: ManagedKnowledgeRetriever, motion: str
) -> None:
    publish(
        store,
        make_record(conditions={"scene_type": "portrait", "subject_motion": ["static", "slow"]}),
    )

    hits = retriever.search(
        "主体留白", conditions={"scene_type": "portrait", "subject_motion": motion}
    )

    assert len(hits) == 1


@pytest.mark.parametrize(
    "context",
    [
        {"scene_type": "landscape", "subject_motion": "static"},
        {"scene_type": "portrait", "subject_motion": "fast"},
        {"scene_type": None, "subject_motion": "static"},
    ],
)
def test_nonmatching_or_unknown_conditions_are_excluded(
    store: KnowledgeStore, retriever: ManagedKnowledgeRetriever, context: dict[str, Any]
) -> None:
    publish(
        store,
        make_record(conditions={"scene_type": "portrait", "subject_motion": ["static", "slow"]}),
    )

    assert retriever.search("主体留白", conditions=context) == []


def test_generic_record_remains_available_without_context(
    store: KnowledgeStore, retriever: ManagedKnowledgeRetriever
) -> None:
    publish(store, make_record("test-generic"))
    publish(store, make_record("test-conditional", conditions={"scene_type": "portrait"}))

    assert [hit.metadata["knowledge_id"] for hit in retriever.search("主体留白")] == [
        "test-generic"
    ]


def test_condition_matching_distinguishes_boolean_and_integer(
    store: KnowledgeStore, retriever: ManagedKnowledgeRetriever
) -> None:
    publish(store, make_record("test-boolean", conditions={"tripod": True}))

    assert len(retriever.search("主体留白", conditions={"tripod": True})) == 1
    assert retriever.search("主体留白", conditions={"tripod": 1}) == []


def test_null_constraint_means_no_declared_restriction(
    store: KnowledgeStore, retriever: ManagedKnowledgeRetriever
) -> None:
    publish(store, make_record(conditions={"scene_type": None}))

    assert len(retriever.search("主体留白")) == 1
    assert len(retriever.query_structured("composition")) == 1


def test_source_version_review_and_hash_are_preserved(
    store: KnowledgeStore, retriever: ManagedKnowledgeRetriever
) -> None:
    revision = publish(store, make_record(version=3, payload={"test_marker": "测试数据"}))

    hit = retriever.search("主体留白")[0]

    assert hit.document_id == "composition/test-record@v3"
    assert hit.source == "合成测试资料"
    assert "结构化资料" in hit.content
    assert "测试数据" in hit.content
    assert hit.metadata == {
        "knowledge_id": "test-record",
        "library_id": "composition",
        "version": "3",
        "kind": "guideline",
        "review_status": "published",
        "source_url": "https://example.com/test-data",
        "source_location": "测试章节 1",
        "source_license": "测试数据，无真实知识内容",
        "reviewer": "测试审核员",
        "content_hash": revision.content_hash,
        "retrieval_backend": "managed_keyword",
    }


def test_new_version_and_retirement_are_visible_without_recreating_retriever(
    store: KnowledgeStore, retriever: ManagedKnowledgeRetriever
) -> None:
    publish(store, make_record())
    assert retriever.search("主体留白")[0].metadata["version"] == "1"
    newer = make_record(version=2, content="测试数据：新版主体留白与构图检索标记。")
    store.save_draft(newer)
    store.submit(newer.knowledge_id)
    store.approve(newer.knowledge_id, reviewer="测试审核员")

    assert retriever.search("主体留白")[0].metadata["version"] == "1"
    store.publish(newer.knowledge_id)
    hits = retriever.search("主体留白")
    assert len(hits) == 1
    assert hits[0].metadata["version"] == "2"
    assert store.get_revision(newer.knowledge_id, 1).status == "retired"
    store.retire(newer.knowledge_id)
    assert retriever.search("主体留白") == []


def test_structured_query_matches_nested_paths_and_preserves_revision(
    store: KnowledgeStore, retriever: ManagedKnowledgeRetriever
) -> None:
    publish(
        store,
        make_record(
            "test-equipment", library_id="equipment", kind="manufacturer_fact",
            payload={"camera": {"model": "TEST-ONLY", "iso": {"min": 100}}, "test": True},
        ),
    )
    publish(store, make_record("test-other-library", payload={"camera": {"model": "TEST-ONLY"}}))

    rows = retriever.query_structured("equipment", {"camera.model": "TEST-ONLY", "camera.iso.min": 100})

    assert len(rows) == 1
    assert rows[0].record.knowledge_id == "test-equipment"
    assert rows[0].status == "published"
    assert rows[0].record.source.name == "合成测试资料"
    assert retriever.query_structured("equipment", {"camera.iso.min": 200}) == []
    assert retriever.query_structured("equipment", {"camera.unknown": None}) == []
    assert retriever.query_structured("equipment", {"camera.model.unknown": "TEST-ONLY"}) == []


@pytest.mark.parametrize(
    "context",
    [None, {}, {"scene_type": "portrait"}, {"scene_type": "landscape", "tripod": True}],
)
def test_structured_query_excludes_unverified_or_mismatched_conditions(
    store: KnowledgeStore,
    retriever: ManagedKnowledgeRetriever,
    context: dict[str, Any] | None,
) -> None:
    publish(
        store,
        make_record(
            library_id="equipment", payload={"model": "TEST-ONLY"},
            conditions={"scene_type": "portrait", "tripod": True},
        ),
    )

    assert retriever.query_structured(
        "equipment", {"model": "TEST-ONLY"}, conditions=context
    ) == []


def test_structured_query_applies_conditions_and_payload_filters_together(
    store: KnowledgeStore, retriever: ManagedKnowledgeRetriever
) -> None:
    publish(
        store,
        make_record(
            library_id="equipment", payload={"model": "TEST-ONLY"},
            conditions={"scene_type": ["portrait", "food"], "tripod": True},
        ),
    )
    context = {"scene_type": "food", "tripod": True}

    assert len(retriever.query_structured(
        "equipment", {"model": "TEST-ONLY"}, conditions=context
    )) == 1
    assert retriever.query_structured("equipment", {"model": "OTHER"}, conditions=context) == []
    assert retriever.query_structured(
        "equipment", {"model": "TEST-ONLY"}, conditions={"scene_type": "food", "tripod": 1}
    ) == []


@pytest.mark.parametrize(
    ("payload_value", "requested_value"),
    [(True, 1), (1, True), ({"value": True}, {"value": 1}), ([True], [1])],
)
def test_structured_matching_does_not_conflate_boolean_and_integer(
    store: KnowledgeStore,
    retriever: ManagedKnowledgeRetriever,
    payload_value: Any,
    requested_value: Any,
) -> None:
    publish(store, make_record(payload={"flag": payload_value}))

    assert retriever.query_structured("composition", {"flag": requested_value}) == []
    assert len(retriever.query_structured("composition", {"flag": payload_value})) == 1


@pytest.mark.parametrize("invalid_top_k", [0, -1, 101, True, False, 1.0, "1", None])
def test_invalid_top_k_is_rejected(
    retriever: ManagedKnowledgeRetriever, invalid_top_k: Any
) -> None:
    with pytest.raises(ValueError, match="top_k"):
        retriever.search("测试数据", top_k=invalid_top_k)


@pytest.mark.parametrize("query", ["", "   ", "！？！"])
def test_empty_token_query_returns_no_hits(
    store: KnowledgeStore, retriever: ManagedKnowledgeRetriever, query: str
) -> None:
    publish(store, make_record())
    assert retriever.search(query) == []


def test_top_k_limits_results(store: KnowledgeStore, retriever: ManagedKnowledgeRetriever) -> None:
    for index in range(5):
        publish(store, make_record(f"test-record-{index}"))

    hits = retriever.search("主体留白", top_k=2)

    assert len(hits) == 2
    assert hits[0].document_id < hits[1].document_id


def test_unknown_library_is_rejected(retriever: ManagedKnowledgeRetriever) -> None:
    with pytest.raises(ValueError, match="知识库"):
        retriever.search("测试数据", libraries=["unknown"])
    with pytest.raises(ValueError, match="知识库"):
        retriever.query_structured("unknown")


@pytest.mark.parametrize("path", ["", ".camera", "camera.", "camera..model", 1])
def test_invalid_structured_paths_are_rejected(
    retriever: ManagedKnowledgeRetriever, path: Any
) -> None:
    with pytest.raises(ValueError, match="点路径"):
        retriever.query_structured("equipment", {path: "测试数据"})
