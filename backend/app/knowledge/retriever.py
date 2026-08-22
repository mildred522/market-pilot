from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent_runtime.followup_evidence import EvidenceMaterial
from app.knowledge.embeddings import DenseEmbeddingProvider
from app.knowledge.query import KnowledgeQuery
from app.knowledge.rerankers import KnowledgeReranker


class KnowledgeRetrievalTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal[
        "hybrid",
        "hybrid_weighted",
        "hybrid_reranked",
        "dense",
        "bm25",
        "curated",
    ]
    candidate_count: int = Field(ge=0)
    selected_chunks: int = Field(ge=0)
    source_count: int = Field(ge=0)
    degradations: tuple[str, ...] = ()
    duration_ms: int = Field(ge=0)


class KnowledgeRetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    facts: tuple[EvidenceMaterial, ...] = ()
    trace: KnowledgeRetrievalTrace


class QdrantHybridKnowledgeRetriever:
    def __init__(
        self,
        *,
        url: str,
        api_key: str,
        collection: str,
        dense_embedder: DenseEmbeddingProvider | None,
        retrieval_mode: Literal[
            "hybrid", "hybrid_weighted", "hybrid_reranked", "dense", "bm25"
        ] = "hybrid",
        reranker: KnowledgeReranker | None = None,
        rerank_limit: int = 12,
        candidate_limit: int = 30,
        timeout_seconds: float = 8.0,
        client=None,
        models_module=None,
    ) -> None:
        if (client is None) != (models_module is None):
            raise ValueError("client and models_module must be supplied together")
        if client is None or models_module is None:
            try:
                from qdrant_client import QdrantClient, models
            except ImportError as error:
                raise RuntimeError(
                    "install backend/requirements-rag.txt to use Qdrant"
                ) from error
            client = QdrantClient(
                url=url,
                api_key=api_key or None,
                cloud_inference=True,
                timeout=timeout_seconds,
            )
            models_module = models
        self._client = client
        self._models = models_module
        self._collection = collection
        self._dense = dense_embedder
        self._retrieval_mode = retrieval_mode
        self._reranker = reranker
        self._rerank_limit = rerank_limit
        self._candidate_limit = candidate_limit

    def retrieve(self, query: KnowledgeQuery) -> KnowledgeRetrievalResult:
        started_at = perf_counter()
        models = self._models
        degradations: list[str] = []
        dense_vector = None
        if self._retrieval_mode != "bm25" and self._dense is not None:
            try:
                dense_vector = self._dense.embed_query(query.text)
            except Exception:
                degradations.append("dense_embedding_unavailable")
        elif self._retrieval_mode != "bm25":
            degradations.append("dense_embedding_unavailable")

        sparse_query = models.Document(
            text=query.text,
            model="qdrant/bm25",
            options={"tokenizer": "multilingual"},
        )
        query_filter = self._build_filter(query)
        try:
            if self._retrieval_mode == "dense":
                if dense_vector is None:
                    raise LookupError("dense embedding is unavailable")
                mode = "dense"
                response = self._client.query_points(
                    collection_name=self._collection,
                    query=dense_vector,
                    using="dense",
                    query_filter=query_filter,
                    limit=self._candidate_limit,
                    with_payload=True,
                )
            elif self._retrieval_mode == "bm25" or dense_vector is None:
                mode = "bm25"
                response = self._client.query_points(
                    collection_name=self._collection,
                    query=sparse_query,
                    using="sparse",
                    query_filter=query_filter,
                    limit=self._candidate_limit,
                    with_payload=True,
                )
            elif self._retrieval_mode == "hybrid_weighted":
                mode = "hybrid_weighted"
                dense_response = self._client.query_points(
                    collection_name=self._collection,
                    query=dense_vector,
                    using="dense",
                    query_filter=query_filter,
                    limit=self._candidate_limit,
                    with_payload=True,
                )
                sparse_response = self._client.query_points(
                    collection_name=self._collection,
                    query=sparse_query,
                    using="sparse",
                    query_filter=query_filter,
                    limit=self._candidate_limit,
                    with_payload=True,
                )
                response_points = _weighted_rrf(
                    dense_response.points,
                    sparse_response.points,
                    dense_weight=1.0,
                    sparse_weight=2.0,
                )
                response = None
            else:
                mode = (
                    "hybrid_reranked"
                    if self._retrieval_mode == "hybrid_reranked"
                    else "hybrid"
                )
                response = self._client.query_points(
                    collection_name=self._collection,
                    prefetch=[
                        models.Prefetch(
                            query=dense_vector,
                            using="dense",
                            limit=self._candidate_limit,
                        ),
                        models.Prefetch(
                            query=sparse_query,
                            using="sparse",
                            limit=self._candidate_limit,
                        ),
                    ],
                    query=models.FusionQuery(fusion=models.Fusion.RRF),
                    query_filter=query_filter,
                    limit=self._candidate_limit,
                    with_payload=True,
                )
        except Exception as error:
            raise LookupError("knowledge index query failed") from error

        if response is not None:
            response_points = response.points
        candidates = [
            point
            for point in response_points
            if _eligible_payload(point.payload or {}, query)
        ]
        if self._retrieval_mode == "hybrid_reranked":
            if self._reranker is None:
                degradations.append("reranker_unavailable")
                mode = "hybrid"
            else:
                try:
                    rerank_candidates = candidates[: self._rerank_limit]
                    scores = self._reranker.score(
                        query.text,
                        [point.payload["raw_text"] for point in rerank_candidates],
                    )
                    candidates = _rerank_points(rerank_candidates, scores) + candidates[
                        self._rerank_limit :
                    ]
                except Exception:
                    degradations.append("reranker_unavailable")
                    mode = "hybrid"
        selected = candidates[: query.limit]
        facts = tuple(_to_evidence(point, mode=mode) for point in selected)
        source_count = len(
            {
                point.payload.get("source_id")
                for point in selected
                if point.payload and point.payload.get("source_id") is not None
            }
        )
        return KnowledgeRetrievalResult(
            facts=facts,
            trace=KnowledgeRetrievalTrace(
                mode=mode,
                candidate_count=len(response_points),
                selected_chunks=len(facts),
                source_count=source_count,
                degradations=tuple(degradations),
                duration_ms=round((perf_counter() - started_at) * 1000),
            ),
        )

    def _build_filter(self, query: KnowledgeQuery):
        models = self._models
        fact_statuses = (
            ["observed", "mixed", "forecast"]
            if query.include_forecasts
            else ["observed", "mixed"]
        )
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="version_status",
                    match=models.MatchValue(value="active"),
                ),
                models.FieldCondition(
                    key="reliability_tier",
                    range=models.Range(lte=query.max_reliability_tier),
                ),
                models.FieldCondition(
                    key="source_type",
                    match=models.MatchAny(any=list(query.allowed_source_types)),
                ),
                models.FieldCondition(
                    key="fact_status",
                    match=models.MatchAny(any=fact_statuses),
                ),
            ]
        )


@dataclass(frozen=True)
class _FusedPoint:
    id: object
    payload: dict
    score: float


def _weighted_rrf(
    dense_points,
    sparse_points,
    *,
    dense_weight: float,
    sparse_weight: float,
    rank_constant: int = 60,
):
    scores: dict[object, float] = {}
    points_by_id = {}
    for points, weight in (
        (dense_points, dense_weight),
        (sparse_points, sparse_weight),
    ):
        for rank, point in enumerate(points, start=1):
            points_by_id[point.id] = point
            scores[point.id] = scores.get(point.id, 0.0) + weight / (
                rank_constant + rank
            )
    return [
        _FusedPoint(
            id=point_id,
            payload=points_by_id[point_id].payload or {},
            score=score,
        )
        for point_id, score in sorted(
            scores.items(), key=lambda item: item[1], reverse=True
        )
    ]


def _rerank_points(points, scores: list[float]):
    if len(points) != len(scores):
        raise ValueError("reranker returned an unexpected score count")
    ranked = sorted(zip(points, scores, strict=True), key=lambda item: item[1], reverse=True)
    return [
        _FusedPoint(id=point.id, payload=point.payload or {}, score=score)
        for point, score in ranked
    ]

def _eligible_payload(payload: dict, query: KnowledgeQuery) -> bool:
    cities = payload.get("cities") or []
    categories = payload.get("categories") or []
    if query.city and cities and query.city not in cities:
        return False
    if (
        query.category
        and categories
        and query.category not in categories
        and payload.get("source_type") != "internal_methodology"
    ):
        return False
    effective_to = payload.get("effective_to_ts")
    if effective_to is not None and effective_to < int(query.as_of.timestamp()):
        return False
    if not query.include_forecasts and payload.get("fact_status") == "forecast":
        return False
    return True


def _to_evidence(point, *, mode: str) -> EvidenceMaterial:
    payload = point.payload or {}
    source_id = payload["source_id"]
    version_id = payload["document_version_id"]
    chunk_id = payload["chunk_id"]
    heading_path = payload.get("heading_path") or []
    title = payload.get("title") or "外部知识"
    label = " > ".join([title, *heading_path])
    limitations = []
    if payload.get("fact_status") in {"forecast", "mixed"}:
        limitations.append("材料包含预测或混合口径，不能表述为已发生事实")
    return EvidenceMaterial(
        canonical_ref=(
            f"external.knowledge.source.{source_id}.version.{version_id}."
            f"chunk.{chunk_id}"
        ),
        source="external_context",
        label=label,
        value=payload["raw_text"],
        limitations=tuple(limitations),
        provenance={
            "title": title,
            "source_key": payload.get("source_key"),
            "publisher": payload.get("publisher"),
            "url": payload.get("source_url"),
            "source_type": payload.get("source_type"),
            "reliability_tier": payload.get("reliability_tier"),
            "published_at_ts": payload.get("published_at_ts"),
            "data_period_start_ts": payload.get("data_period_start_ts"),
            "data_period_end_ts": payload.get("data_period_end_ts"),
            "fact_status": payload.get("fact_status"),
            "chunk_id": chunk_id,
            "page_start": payload.get("page_start"),
            "page_end": payload.get("page_end"),
            "retrieval_score": point.score,
            "retrieval_mode": mode,
            "content_hash": payload.get("content_hash"),
        },
    )
