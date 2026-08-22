from __future__ import annotations

from sqlalchemy.orm import Session

from app.knowledge.contracts import KnowledgeRagSettings
from app.knowledge.embeddings import QwenSentenceTransformerEmbeddings
from app.knowledge.fact_repository import ReviewedKnowledgeFactRepository
from app.knowledge.rerankers import QwenCrossEncoderReranker
from app.knowledge.retriever import QdrantHybridKnowledgeRetriever
from app.knowledge.service import KnowledgeRetrievalService


def build_knowledge_retrieval_service(
    db: Session,
    settings: KnowledgeRagSettings,
) -> KnowledgeRetrievalService | None:
    """Build the optional retrieval boundary without connecting eagerly."""
    if not settings.enabled:
        return None
    backend = None
    try:
        backend = QdrantHybridKnowledgeRetriever(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            collection=settings.collection,
            dense_embedder=QwenSentenceTransformerEmbeddings(settings.dense_model),
            retrieval_mode=(
                "hybrid_reranked" if settings.rerank_enabled else "hybrid"
            ),
            reranker=(
                QwenCrossEncoderReranker(settings.reranker_model)
                if settings.rerank_enabled
                else None
            ),
            timeout_seconds=settings.retrieval_timeout_seconds,
        )
    except RuntimeError:
        # Approved facts remain usable when optional RAG packages are absent.
        pass
    return KnowledgeRetrievalService(
        settings,
        backend=backend,
        fact_provider=ReviewedKnowledgeFactRepository(db),
    )
