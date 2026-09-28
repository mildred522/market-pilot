from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent_runtime.followup_evidence import EvidenceRetrievalContext
from app.db.models import Base, KnowledgeFact
from app.knowledge.contracts import (
    KnowledgeDocumentVersionInput,
    KnowledgeFactInput,
    KnowledgeRagSettings,
    KnowledgeSourceInput,
)
from app.knowledge.fact_repository import ReviewedKnowledgeFactRepository
from app.knowledge.query import KnowledgeQueryCompiler
from app.knowledge.service import KnowledgeRetrievalService
from app.knowledge.source_repository import KnowledgeSourceRepository


NOW = datetime(2026, 8, 20, 12, tzinfo=UTC)


def test_repository_versions_sources_idempotently_and_persists_reviewed_facts():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        repository = KnowledgeSourceRepository(db)
        source = repository.upsert_source(
            KnowledgeSourceInput(
                source_key="chengdu-statistics-2025",
                title="2025年成都市经济运行情况",
                publisher="成都市统计局",
                source_type="official_statistics",
                canonical_url="https://example.gov.cn/chengdu-2025",
                reliability_tier=1,
                default_city="成都",
                default_category="餐饮",
            )
        )
        first, created = repository.register_version(
            source.id, _version("sha256:first")
        )
        duplicate, duplicate_created = repository.register_version(
            source.id, _version("sha256:first")
        )
        second, second_created = repository.register_version(
            source.id, _version("sha256:second")
        )
        fact = repository.add_fact(
            first.id,
            KnowledgeFactInput(
                fact_key="food_service_revenue_growth",
                label="餐饮收入同比增速",
                value=7.2,
                unit="percent",
                geography="成都",
                category="餐饮",
                observed_or_forecast="observed",
                review_status="approved",
            ),
        )
        job = repository.start_job(second.id)
        repository.finish_job(
            job,
            status="completed",
            stage="activated",
            chunks_parsed=12,
            chunks_indexed=12,
            finished_at=NOW,
        )
        db.commit()

        stored_fact = db.scalar(
            select(KnowledgeFact).where(KnowledgeFact.id == fact.id)
        )

        first_id = first.id
        duplicate_id = duplicate.id
        second_version_number = second.version_number
        stored_value = stored_fact.value_json if stored_fact is not None else None
        job_status = job.status
        indexed_chunks = job.chunks_indexed

    assert created is True
    assert duplicate_created is False
    assert duplicate_id == first_id
    assert second_created is True
    assert second_version_number == 2
    assert stored_fact is not None
    assert stored_value == 7.2
    assert job_status == "completed"
    assert indexed_chunks == 12


def test_source_contract_rejects_unstable_source_keys():
    with pytest.raises(ValidationError):
        KnowledgeSourceInput(
            source_key="成都 统计",
            title="测试",
            publisher="测试来源",
            source_type="article",
            canonical_url="https://example.com",
            reliability_tier=2,
        )


def test_replace_facts_is_idempotent_for_document_version():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        repository = KnowledgeSourceRepository(db)
        source = repository.upsert_source(
            KnowledgeSourceInput(
                source_key="replace-facts",
                title="事实替换测试",
                publisher="测试来源",
                source_type="official_statistics",
                canonical_url="https://example.com/facts",
                reliability_tier=1,
            )
        )
        version, _ = repository.register_version(source.id, _version("sha256:replace"))
        first = KnowledgeFactInput(
            fact_key="revenue",
            label="餐饮收入",
            value=100,
            unit="亿元",
            observed_or_forecast="observed",
        )
        replacement = first.model_copy(update={"value": 120})

        repository.replace_facts(version.id, (first,))
        repository.replace_facts(version.id, (replacement,))
        db.commit()
        stored = list(db.scalars(select(KnowledgeFact)))

    assert len(stored) == 1
    assert stored[0].value_json == 120


def test_approve_pending_facts_does_not_change_rejected_facts():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        repository = KnowledgeSourceRepository(db)
        source = repository.upsert_source(
            KnowledgeSourceInput(
                source_key="approve-facts",
                title="事实审核测试",
                publisher="测试来源",
                source_type="official_statistics",
                canonical_url="https://example.com/approve-facts",
                reliability_tier=1,
            )
        )
        version, _ = repository.register_version(source.id, _version("sha256:approve"))
        pending = KnowledgeFactInput(
            fact_key="pending",
            label="待审核事实",
            value=100,
            observed_or_forecast="observed",
        )
        rejected = pending.model_copy(
            update={"fact_key": "rejected", "label": "已拒绝事实", "review_status": "rejected"}
        )
        repository.replace_facts(version.id, (pending, rejected))

        changed = repository.approve_pending_facts(version.id)
        db.commit()
        statuses = {
            fact.fact_key: fact.review_status
            for fact in db.scalars(select(KnowledgeFact))
        }

    assert changed == 1
    assert statuses == {"pending": "approved", "rejected": "rejected"}


def test_reviewed_fact_repository_applies_active_city_and_forecast_policy():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        repository = KnowledgeSourceRepository(db)
        source = repository.upsert_source(
            KnowledgeSourceInput(
                source_key="reviewed-chengdu-facts",
                title="成都审核数据",
                publisher="成都市统计局",
                source_type="official_statistics",
                canonical_url="https://example.gov.cn/facts",
                reliability_tier=1,
            )
        )
        version, _ = repository.register_version(source.id, _version("sha256:facts"))
        version.index_status = "active"
        repository.add_fact(
            version.id,
            KnowledgeFactInput(
                fact_key="revenue_growth",
                label="餐饮收入增速",
                value=6.2,
                unit="percent_yoy",
                geography="成都",
                category="新茶饮",
                observed_or_forecast="observed",
                review_status="approved",
            ),
        )
        repository.add_fact(
            version.id,
            KnowledgeFactInput(
                fact_key="future_growth",
                label="未来市场增速",
                value=19.7,
                unit="percent_cagr",
                geography="成都",
                category="新茶饮",
                observed_or_forecast="forecast",
                review_status="approved",
            ),
        )
        db.flush()
        context = _context().model_copy(
            update={
                "question": "成都奶茶当前情况如何？",
                "project_profile": {"city": "成都", "category": "新茶饮"},
            }
        )
        query = KnowledgeQueryCompiler().compile(context)

        facts = ReviewedKnowledgeFactRepository(db).retrieve(query)

    assert len(facts) == 1
    assert facts[0].value == 6.2
    assert facts[0].provenance["review_status"] == "approved"


def test_disabled_knowledge_service_never_calls_backend():
    backend = FailingBackend()
    service = KnowledgeRetrievalService(KnowledgeRagSettings(), backend)

    assert service.available is False
    assert service.health().status == "disabled"
    with pytest.raises(LookupError, match="disabled"):
        service.retrieve(_context())
    assert backend.calls == 0


def _version(content_hash: str) -> KnowledgeDocumentVersionInput:
    return KnowledgeDocumentVersionInput(
        content_hash=content_hash,
        published_at=NOW,
        data_period_start=datetime(2025, 1, 1, tzinfo=UTC),
        data_period_end=datetime(2025, 12, 31, tzinfo=UTC),
        fact_status="observed",
        raw_storage_path="raw/chengdu-statistics-2025/report.pdf",
        media_type="application/pdf",
        parser_version="docling-2",
        chunker_version="knowledge-v1",
        embedding_model="Qwen/Qwen3-Embedding-0.6B",
    )


def _context() -> EvidenceRetrievalContext:
    return EvidenceRetrievalContext(
        question="成都餐饮收入趋势如何？",
        purpose="补充行业趋势",
        success_condition="返回带发布日期的统计事实",
        requirement="required",
        project_profile={"city": "成都", "category": "餐饮"},
        as_of=NOW,
    )


class FailingBackend:
    def __init__(self) -> None:
        self.calls = 0

    def retrieve(self, _context):
        self.calls += 1
        raise AssertionError("disabled service called its backend")
