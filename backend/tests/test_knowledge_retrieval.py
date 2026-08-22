import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent_runtime.followup_evidence import (
    EvidenceMaterial,
    EvidenceRetrievalContext,
)
from app.knowledge.contracts import KnowledgeRagSettings
from app.knowledge.query import KnowledgeQueryCompiler
from app.knowledge.embeddings import QwenSentenceTransformerEmbeddings
from app.knowledge.retriever import QdrantHybridKnowledgeRetriever
from app.knowledge.service import KnowledgeRetrievalService


NOW = datetime(2026, 8, 20, 12, tzinfo=UTC)


def test_query_compiler_normalizes_profile_and_preserves_freshness_intent():
    query = KnowledgeQueryCompiler().compile(
        _context("结合成都最新趋势，分析奶茶未来潜力")
    )

    assert query.city == "成都"
    assert query.category == "新茶饮"
    assert query.requires_current is True
    assert query.include_forecasts is True
    assert query.max_reliability_tier == 2
    assert "检索目的：补充可核验的行业背景" in query.text


def test_query_compiler_matches_initial_labelled_cases():
    cases = json.loads(
        (
            Path(__file__).parents[1]
            / "evals"
            / "cases"
            / "knowledge_retrieval.json"
        ).read_text(encoding="utf-8")
    )
    compiler = KnowledgeQueryCompiler()

    for case in cases:
        context = EvidenceRetrievalContext(
            question=case["question"],
            purpose="补充可核验的行业背景",
            success_condition="返回带来源、日期和口径的材料",
            requirement="required",
            project_profile=case["profile"],
            as_of=NOW,
        )
        query = compiler.compile(context)
        expected = case["expected"]
        assert query.city == expected["city"], case["id"]
        assert query.category == expected["category"], case["id"]
        assert query.requires_current == expected["requires_current"], case["id"]
        assert query.include_forecasts == expected["include_forecasts"], case["id"]
        if "source_types" in expected:
            assert list(query.allowed_source_types) == expected["source_types"], case[
                "id"
            ]


def test_hybrid_retrieval_uses_rrf_and_filters_geography_after_search():
    client = FakeSearchClient(
        [
            _point(1, city="成都", fact_status="observed"),
            _point(2, city=None, fact_status="forecast"),
            _point(3, city="北京", fact_status="observed"),
        ]
    )
    retriever = QdrantHybridKnowledgeRetriever(
        url="http://qdrant.test:6333",
        api_key="",
        collection="knowledge_test",
        dense_embedder=FakeEmbedder(),
        client=client,
        models_module=FakeModels,
    )
    query = KnowledgeQueryCompiler().compile(
        _context("结合成都最新趋势，分析奶茶未来潜力")
    )

    result = retriever.retrieve(query)

    assert result.trace.mode == "hybrid"
    assert result.trace.candidate_count == 3
    assert result.trace.selected_chunks == 2
    assert result.trace.source_count == 2
    assert result.trace.degradations == ()
    assert len(client.last_query["prefetch"]) == 2
    assert client.last_query["query"].fusion == "rrf"
    assert [fact.provenance["fact_status"] for fact in result.facts] == [
        "observed",
        "forecast",
    ]
    assert "预测或混合口径" in result.facts[1].limitations[0]


def test_retrieval_degrades_to_bm25_and_retains_mixed_evidence_with_warning():
    client = FakeSearchClient(
        [
            _point(1, city="成都", fact_status="observed"),
            _point(2, city="成都", fact_status="mixed"),
        ]
    )
    retriever = QdrantHybridKnowledgeRetriever(
        url="http://qdrant.test:6333",
        api_key="",
        collection="knowledge_test",
        dense_embedder=None,
        client=client,
        models_module=FakeModels,
    )

    result = retriever.retrieve(
        KnowledgeQueryCompiler().compile(_context("成都奶茶当前情况如何"))
    )

    assert result.trace.mode == "bm25"
    assert result.trace.degradations == ("dense_embedding_unavailable",)
    assert len(result.facts) == 2
    assert "预测或混合口径" in result.facts[1].limitations[0]
    assert client.last_query["using"] == "sparse"
    assert client.last_query["query"].options == {"tokenizer": "multilingual"}


def test_dense_only_retrieval_uses_named_dense_vector():
    client = FakeSearchClient([_point(1, city="成都", fact_status="observed")])
    retriever = QdrantHybridKnowledgeRetriever(
        url="http://qdrant.test:6333",
        api_key="",
        collection="knowledge_test",
        dense_embedder=FakeEmbedder(),
        retrieval_mode="dense",
        client=client,
        models_module=FakeModels,
    )

    result = retriever.retrieve(
        KnowledgeQueryCompiler().compile(_context("成都奶茶当前情况如何"))
    )

    assert result.trace.mode == "dense"
    assert client.last_query["using"] == "dense"
    assert client.last_query["query"] == [0.1, 0.2, 0.3]
    assert result.facts[0].provenance["retrieval_mode"] == "dense"


def test_weighted_hybrid_gives_sparse_ranking_twice_the_rrf_weight():
    points = {
        "dense": [
            _point(2, city="成都", fact_status="observed"),
            _point(1, city="成都", fact_status="observed"),
            _point(3, city="成都", fact_status="observed"),
        ],
        "sparse": [
            _point(1, city="成都", fact_status="observed"),
            _point(3, city="成都", fact_status="observed"),
            _point(2, city="成都", fact_status="observed"),
        ],
    }
    client = BranchingSearchClient(points)
    retriever = QdrantHybridKnowledgeRetriever(
        url="http://qdrant.test:6333",
        api_key="",
        collection="knowledge_test",
        dense_embedder=FakeEmbedder(),
        retrieval_mode="hybrid_weighted",
        client=client,
        models_module=FakeModels,
    )

    result = retriever.retrieve(
        KnowledgeQueryCompiler().compile(_context("成都奶茶当前情况如何"))
    )

    assert result.trace.mode == "hybrid_weighted"
    assert len(client.queries) == 2
    assert result.facts[0].canonical_ref.startswith("external.knowledge.source.1.")
    assert result.facts[0].provenance["retrieval_mode"] == "hybrid_weighted"


def test_hybrid_reranker_reorders_candidates_by_cross_encoder_score():
    client = FakeSearchClient(
        [
            _point(1, city="成都", fact_status="observed"),
            _point(2, city="成都", fact_status="observed"),
            _point(3, city="成都", fact_status="observed"),
        ]
    )
    retriever = QdrantHybridKnowledgeRetriever(
        url="http://qdrant.test:6333",
        api_key="",
        collection="knowledge_test",
        dense_embedder=FakeEmbedder(),
        retrieval_mode="hybrid_reranked",
        reranker=FakeReranker([0.1, 0.9, 0.2]),
        client=client,
        models_module=FakeModels,
    )

    result = retriever.retrieve(
        KnowledgeQueryCompiler().compile(_context("成都奶茶当前情况如何"))
    )

    assert result.trace.mode == "hybrid_reranked"
    assert result.facts[0].canonical_ref.startswith("external.knowledge.source.2.")
    assert result.facts[0].provenance["retrieval_mode"] == "hybrid_reranked"


def test_service_returns_reviewed_facts_when_qdrant_is_unavailable():
    fact = EvidenceMaterial(
        canonical_ref="external.knowledge.source.1.version.2.fact.revenue_growth",
        source="external_context",
        label="餐饮收入增速",
        value=6.2,
        unit="percent_yoy",
        provenance={"url": "https://example.gov.cn/facts"},
    )
    service = KnowledgeRetrievalService(
        KnowledgeRagSettings(enabled=True),
        backend=UnavailableBackend(),
        fact_provider=FakeFactProvider((fact,)),
    )

    result = service.retrieve(_context("成都奶茶当前情况如何"))

    assert result.trace.mode == "curated"
    assert result.trace.degradations == ("qdrant_unavailable",)
    assert result.facts == (fact,)


def test_dense_model_load_is_local_only_and_failure_is_circuit_broken(
    monkeypatch, tmp_path
):
    calls = []

    class FailingSentenceTransformer:
        def __init__(self, model_name, **options):
            calls.append((model_name, options))
            raise OSError("model is not cached")

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=FailingSentenceTransformer),
    )
    model_path = tmp_path / "cached-model"
    model_path.mkdir()
    embedder = QwenSentenceTransformerEmbeddings(str(model_path))

    with pytest.raises(RuntimeError, match="unavailable"):
        embedder.embed_query("第一次")
    with pytest.raises(RuntimeError, match="unavailable"):
        embedder.embed_query("第二次")

    assert len(calls) == 1
    assert calls[0][1]["local_files_only"] is True


def _context(question: str) -> EvidenceRetrievalContext:
    return EvidenceRetrievalContext(
        question=question,
        purpose="补充可核验的行业背景",
        success_condition="返回带来源、日期和口径的材料",
        requirement="required",
        project_profile={"city": "chengdu", "category": "milk-tea"},
        as_of=NOW,
    )


def _point(identifier: int, *, city: str | None, fact_status: str):
    cities = [city] if city else []
    return SimpleNamespace(
        id=identifier,
        score=0.8,
        payload={
            "source_id": identifier,
            "document_version_id": identifier + 10,
            "chunk_id": f"kv{identifier + 10}-c0000",
            "title": f"来源 {identifier}",
            "publisher": "测试发布方",
            "source_url": f"https://example.com/{identifier}",
            "source_type": "industry_association",
            "reliability_tier": 2,
            "published_at_ts": int(NOW.timestamp()),
            "data_period_start_ts": int(NOW.timestamp()) - 86400,
            "data_period_end_ts": int(NOW.timestamp()),
            "effective_to_ts": None,
            "fact_status": fact_status,
            "cities": cities,
            "categories": ["新茶饮"],
            "heading_path": ["市场趋势"],
            "raw_text": f"第 {identifier} 条行业资料",
            "content_hash": str(identifier) * 64,
        },
    )


class FakeEmbedder:
    dimensions = 1024

    def embed_query(self, _text):
        return [0.1, 0.2, 0.3]


class FakeReranker:
    def __init__(self, scores):
        self.scores = scores

    def score(self, _query, _documents):
        return self.scores


class ModelRecord:
    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)


class FakeModels:
    Document = ModelRecord
    Prefetch = ModelRecord
    FusionQuery = ModelRecord
    Filter = ModelRecord
    FieldCondition = ModelRecord
    MatchValue = ModelRecord
    MatchAny = ModelRecord
    Range = ModelRecord

    class Fusion:
        RRF = "rrf"


class FakeSearchClient:
    def __init__(self, points):
        self.points = points
        self.last_query = None

    def query_points(self, **values):
        self.last_query = values
        return SimpleNamespace(points=self.points)


class BranchingSearchClient:
    def __init__(self, points_by_vector):
        self.points_by_vector = points_by_vector
        self.queries = []

    def query_points(self, **values):
        self.queries.append(values)
        return SimpleNamespace(points=self.points_by_vector[values["using"]])


class UnavailableBackend:
    def retrieve(self, _query):
        raise LookupError("qdrant unavailable")


class FakeFactProvider:
    def __init__(self, facts):
        self.facts = facts

    def retrieve(self, _query):
        return self.facts
