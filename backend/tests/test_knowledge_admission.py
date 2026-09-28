from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base
from app.knowledge.admission import KnowledgeAdmissionPolicy
from app.knowledge.chunker import DeterministicKnowledgeChunker
from app.knowledge.contracts import KnowledgeSourceInput
from app.knowledge.document import AcquiredDocument, ParsedBlock, ParsedDocument
from app.knowledge.index_store import InMemoryKnowledgeIndexStore
from app.knowledge.ingestion import KnowledgeIngestionCoordinator
from app.knowledge.manifest import KnowledgeAcquisition, KnowledgeManifestEntry
from app.knowledge.parser import MarkdownDocumentParser
from app.knowledge.storage import KnowledgeStorage


NOW = datetime(2026, 8, 24, tzinfo=UTC)


def test_source_routes_separate_qdrant_from_live_and_private_data():
    policy = KnowledgeAdmissionPolicy()

    statistics = policy.classify(_entry("government_statistics"))
    map_source = policy.classify(_entry("map_platform"))
    merchant = policy.classify(_entry("merchant_operating_data"))
    unknown = policy.classify(_entry("unreviewed_blog"))

    assert statistics.accepted_for_qdrant
    assert statistics.route == "rag_and_structured_fact"
    assert statistics.extract_structured_facts
    assert map_source.route == "live_tool"
    assert map_source.requires_ttl
    assert map_source.reason_codes == ("source_requires_live_tool",)
    assert merchant.route == "private_analytics"
    assert unknown.route == "manual_review"
    assert unknown.reason_codes == ("unknown_source_type_requires_review",)


def test_document_quality_rejects_shell_pages_and_damaged_chinese_pdf():
    policy = KnowledgeAdmissionPolicy()
    short = ParsedDocument(
        title="空壳页",
        blocks=(ParsedBlock(kind="paragraph", text="请启用 JavaScript。"),),
    )
    damaged_pdf = ParsedDocument(
        title="成都统计公报",
        blocks=(
            ParsedBlock(
                kind="paragraph",
                text=("2025 GDP 24763.6 5.8% retail 11434.1 5.5% " * 12),
                page_start=1,
                page_end=1,
            ),
        ),
    )

    short_decision = policy.assess(
        _entry("regulation"), _document("text/html"), short
    )
    pdf_decision = policy.assess(
        _entry("government_statistics"),
        _document("application/pdf"),
        damaged_pdf,
    )

    assert not short_decision.accepted_for_qdrant
    assert "insufficient_indexable_text" in short_decision.reason_codes
    assert not pdf_decision.accepted_for_qdrant
    assert "chinese_pdf_text_loss" in pdf_decision.reason_codes


def test_document_quality_accepts_grounded_text_and_emits_extraction_hint():
    text = (
        "成都市餐饮市场统计显示，2025年餐饮收入达到一百亿元。"
        "本段同时说明统计范围、调查对象和数据期间，避免将预测值当成观测值。"
    ) * 5
    decision = KnowledgeAdmissionPolicy().assess(
        _entry("government_statistics"),
        _document("text/html"),
        ParsedDocument(
            title="成都餐饮统计",
            blocks=(ParsedBlock(kind="paragraph", text=text),),
        ),
    )

    assert decision.accepted_for_qdrant
    assert decision.quality is not None
    assert decision.quality.cjk_ratio > 0.03
    assert decision.route == "rag_and_structured_fact"


def test_ingestion_rejects_live_source_before_loading(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        coordinator = KnowledgeIngestionCoordinator(
            db,
            loader=ExplodingLoader(),
            storage=KnowledgeStorage(tmp_path / "storage"),
            parser=MarkdownDocumentParser(),
            chunker=DeterministicKnowledgeChunker(),
            index_store=InMemoryKnowledgeIndexStore(),
            embedding_model="Qwen/Qwen3-Embedding-0.6B",
        )

        result = coordinator.ingest(
            _entry("map_platform"), manifest_directory=tmp_path
        )

    assert result.status == "rejected"
    assert result.admission_route == "live_tool"
    assert result.error_code == "source_requires_live_tool"
    assert result.document_version_id is None


def _entry(source_type: str) -> KnowledgeManifestEntry:
    return KnowledgeManifestEntry(
        source=KnowledgeSourceInput(
            source_key=f"test-{source_type.replace('_', '-')}",
            title="成都餐饮测试材料",
            publisher="测试发布方",
            source_type=source_type,
            canonical_url="https://example.com/source",
            reliability_tier=1,
            default_city="成都",
            default_category="餐饮",
        ),
        acquisition=KnowledgeAcquisition(
            local_path="source.md",
            allowed_media_types=("text/markdown",),
        ),
        published_at=NOW,
        fact_status="observed",
        cities=("成都",),
        categories=("餐饮",),
    )


def _document(media_type: str) -> AcquiredDocument:
    return AcquiredDocument(
        content=b"test",
        media_type=media_type,
        filename="source.pdf" if media_type == "application/pdf" else "source.html",
        sha256="a" * 64,
    )


class ExplodingLoader:
    def acquire(self, _entry, *, manifest_directory: Path):
        raise AssertionError("non-indexable source must be rejected before acquisition")
