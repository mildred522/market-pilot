from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.agent_runtime.followup_evidence import EvidenceMaterial
from app.db.models import (
    KnowledgeDocumentVersion,
    KnowledgeFact,
    KnowledgeSource,
)
from app.knowledge.query import KnowledgeQuery


class ReviewedKnowledgeFactRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def retrieve(self, query: KnowledgeQuery) -> tuple[EvidenceMaterial, ...]:
        statement = (
            select(KnowledgeFact, KnowledgeDocumentVersion, KnowledgeSource)
            .join(
                KnowledgeDocumentVersion,
                KnowledgeDocumentVersion.id == KnowledgeFact.document_version_id,
            )
            .join(
                KnowledgeSource,
                KnowledgeSource.id == KnowledgeDocumentVersion.source_id,
            )
            .where(
                KnowledgeFact.review_status == "approved",
                KnowledgeDocumentVersion.index_status == "active",
                KnowledgeSource.status == "active",
                KnowledgeSource.reliability_tier <= query.max_reliability_tier,
                KnowledgeSource.source_type.in_(query.allowed_source_types),
                or_(
                    KnowledgeFact.valid_from.is_(None),
                    KnowledgeFact.valid_from <= query.as_of,
                ),
                or_(
                    KnowledgeFact.valid_to.is_(None),
                    KnowledgeFact.valid_to >= query.as_of,
                ),
            )
            .order_by(
                KnowledgeSource.reliability_tier,
                KnowledgeDocumentVersion.published_at.desc(),
                KnowledgeFact.id,
            )
            .limit(query.limit)
        )
        if not query.include_forecasts:
            statement = statement.where(
                KnowledgeFact.observed_or_forecast == "observed"
            )
        if query.city:
            statement = statement.where(
                or_(
                    KnowledgeFact.geography.is_(None),
                    KnowledgeFact.geography == query.city,
                )
            )
        if query.category:
            statement = statement.where(
                or_(
                    KnowledgeFact.category.is_(None),
                    KnowledgeFact.category == query.category,
                )
            )
        return tuple(
            _to_evidence(fact, version, source)
            for fact, version, source in self._db.execute(statement).all()
        )


def _to_evidence(
    fact: KnowledgeFact,
    version: KnowledgeDocumentVersion,
    source: KnowledgeSource,
) -> EvidenceMaterial:
    limitations = []
    if fact.observed_or_forecast == "forecast":
        limitations.append("该值为预测，不能表述为已发生事实")
    return EvidenceMaterial(
        canonical_ref=(
            f"external.knowledge.source.{source.id}.version.{version.id}."
            f"fact.{fact.fact_key}"
        ),
        source="external_context",
        label=fact.label,
        value=fact.value_json,
        unit=fact.unit,
        limitations=tuple(limitations),
        provenance={
            "title": source.title,
            "publisher": source.publisher,
            "url": source.canonical_url,
            "source_type": source.source_type,
            "reliability_tier": source.reliability_tier,
            "published_at": (
                version.published_at.isoformat() if version.published_at else None
            ),
            "data_period_start": (
                version.data_period_start.isoformat()
                if version.data_period_start
                else None
            ),
            "data_period_end": (
                version.data_period_end.isoformat() if version.data_period_end else None
            ),
            "fact_status": fact.observed_or_forecast,
            "geography": fact.geography,
            "category": fact.category,
            "source_chunk_id": fact.source_chunk_id,
            "review_status": fact.review_status,
        },
    )
