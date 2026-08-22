from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    KnowledgeDocumentVersion,
    KnowledgeIngestionJob,
)
from app.knowledge.chunker import DeterministicKnowledgeChunker
from app.knowledge.document import AcquiredDocument
from app.knowledge.index_store import InMemoryKnowledgeIndexStore
from app.knowledge.ingestion import KnowledgeIngestionCoordinator
from app.knowledge.manifest import (
    KnowledgeAcquisition,
    KnowledgeManifest,
    KnowledgeManifestEntry,
    load_knowledge_manifest,
)
from app.knowledge.parser import (
    KnowledgeParseError,
    MarkdownDocumentParser,
    _is_html_boilerplate,
)
from app.knowledge.storage import (
    KnowledgeAcquisitionError,
    KnowledgeStorage,
    SecureDocumentLoader,
)
from app.knowledge.contracts import KnowledgeSourceInput


NOW = datetime(2026, 8, 20, 12, tzinfo=UTC)


def test_manifest_rejects_duplicate_sources_and_escaping_paths():
    entry = _entry()
    with pytest.raises(ValidationError, match="unique"):
        KnowledgeManifest(documents=(entry, entry))
    with pytest.raises(ValidationError, match="relative"):
        KnowledgeAcquisition(
            local_path="../private.txt",
            allowed_media_types=("text/plain",),
        )


def test_seed_manifest_contains_five_reviewed_unique_source_types():
    manifest = load_knowledge_manifest(
        Path(__file__).parents[1] / "data" / "knowledge" / "seed-manifest.json"
    )

    assert len(manifest.documents) == 5
    assert len({item.source.source_key for item in manifest.documents}) == 5
    assert {item.source.source_type for item in manifest.documents} >= {
        "government_statistics",
        "industry_association",
        "listed_company_filing",
        "internal_methodology",
    }


def test_storage_rejects_root_escape_and_hashes_local_document(tmp_path):
    document_path = tmp_path / "source.md"
    document_path.write_text("# 成都餐饮\n\n餐饮收入保持增长。", encoding="utf-8")
    loader = SecureDocumentLoader()
    document = loader.acquire(_entry(), manifest_directory=tmp_path)
    storage = KnowledgeStorage(tmp_path / "storage")

    relative = storage.store_raw(source_key="chengdu-test", document=document)

    assert relative.startswith("raw/chengdu-test/")
    assert storage.resolve(relative).read_bytes() == document.content
    with pytest.raises(KnowledgeAcquisitionError, match="escapes"):
        storage.resolve("../outside.md")


def test_loader_rejects_private_hosts_before_requesting_content():
    acquisition = KnowledgeAcquisition(
        url="http://internal.example/report.pdf",
        allowed_media_types=("application/pdf",),
    )
    entry = _entry().model_copy(update={"acquisition": acquisition})
    loader = SecureDocumentLoader(
        dns_resolver=lambda *_args: [
            (2, 1, 6, "", ("127.0.0.1", 80)),
        ]
    )

    with pytest.raises(KnowledgeAcquisitionError, match="private network"):
        loader.acquire(entry, manifest_directory=Path("."))


def test_loader_only_allows_proxy_fake_ip_range_when_explicitly_enabled():
    fake_ip_resolver = lambda *_args: [(2, 1, 6, "", ("198.18.0.42", 443))]
    default_loader = SecureDocumentLoader(dns_resolver=fake_ip_resolver)
    proxy_loader = SecureDocumentLoader(
        dns_resolver=fake_ip_resolver,
        allow_proxy_fake_ip=True,
    )

    with pytest.raises(KnowledgeAcquisitionError, match="private network"):
        default_loader._verify_public_host("reviewed.example", 443)
    proxy_loader._verify_public_host("reviewed.example", 443)

    private_loader = SecureDocumentLoader(
        dns_resolver=lambda *_args: [(2, 1, 6, "", ("10.0.0.8", 443))],
        allow_proxy_fake_ip=True,
    )
    with pytest.raises(KnowledgeAcquisitionError, match="private network"):
        private_loader._verify_public_host("internal.example", 443)


def test_parser_and_chunker_produce_stable_contextualized_ids(tmp_path):
    document_path = tmp_path / "source.md"
    document_path.write_text(
        "# 市场大盘\n\n成都餐饮收入增长。\n\n## 消费趋势\n\n健康原料受到关注。",
        encoding="utf-8",
    )
    acquired = SecureDocumentLoader().acquire(
        _entry(), manifest_directory=tmp_path
    )
    parsed = MarkdownDocumentParser().parse(acquired, title="成都餐饮测试资料")
    source, version = _persisted_source_and_version()
    chunker = DeterministicKnowledgeChunker()

    first = chunker.chunk(
        parsed,
        entry=_entry(),
        source=source,
        version=version,
    )
    second = chunker.chunk(
        parsed,
        entry=_entry(),
        source=source,
        version=version,
    )

    assert [chunk.point_id for chunk in first] == [chunk.point_id for chunk in second]
    assert first[0].retrieval_text.startswith("[地区: 成都]\n[品类: 餐饮]")
    assert first[0].payload["version_status"] == "staging"
    assert first[0].payload["source_key"] == "chengdu-test"


def test_markdown_parser_keeps_table_header_and_rows_in_one_atomic_block():
    content = (
        "# 门店统计\n\n"
        "| 品类 | 门店数 |\n"
        "| --- | ---: |\n"
        "| 茶饮 | 12 |\n"
    ).encode()
    parsed = MarkdownDocumentParser().parse(
        AcquiredDocument(
            content=content,
            media_type="text/markdown",
            filename="table.md",
            sha256="a" * 64,
        ),
        title="门店统计",
    )

    assert len(parsed.blocks) == 1
    assert parsed.blocks[0].kind == "table"
    assert "| 品类 | 门店数 |" in parsed.blocks[0].text
    assert "| 茶饮 | 12 |" in parsed.blocks[0].text


def test_html_boilerplate_filter_is_conservative():
    assert _is_html_boilerplate("简体中文 / 繁體中文")
    assert _is_html_boilerplate("[English Version](\\en-US\\about-us)")
    assert _is_html_boilerplate("[新闻中心](\\news) *|* [零售业务](\\retail)")
    assert _is_html_boilerplate("img")
    assert not _is_html_boilerplate("市场规模：2023年预计达到1498亿元")


def test_ingestion_is_idempotent_and_failure_keeps_previous_version_active(tmp_path):
    document_path = tmp_path / "source.md"
    document_path.write_text("# 市场\n\n第一版客观资料。", encoding="utf-8")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    index = InMemoryKnowledgeIndexStore()
    with Session(engine) as db:
        coordinator = _coordinator(db, tmp_path, index, MarkdownDocumentParser())

        first = coordinator.ingest(_entry(), manifest_directory=tmp_path)
        duplicate = coordinator.ingest(_entry(), manifest_directory=tmp_path)

        assert first.status == "ingested"
        assert duplicate.status == "unchanged"
        assert duplicate.document_version_id == first.document_version_id
        assert db.scalar(select(func.count(KnowledgeDocumentVersion.id))) == 1
        assert index.count(first.document_version_id) == first.chunks_indexed

        document_path.write_text("# 市场\n\n第二版资料。", encoding="utf-8")
        failed = _coordinator(db, tmp_path, index, FailingParser()).ingest(
            _entry(), manifest_directory=tmp_path
        )
        versions = list(
            db.scalars(
                select(KnowledgeDocumentVersion).order_by(
                    KnowledgeDocumentVersion.version_number
                )
            )
        )
        jobs = list(db.scalars(select(KnowledgeIngestionJob)))

    assert failed.status == "failed"
    assert failed.error_code == "knowledge_parse_error"
    assert [version.index_status for version in versions] == ["active", "failed"]
    assert index.version_status[first.document_version_id] == "active"
    assert index.count(failed.document_version_id) == 0
    assert [job.status for job in jobs] == ["completed", "failed"]


def test_index_cleanup_failure_is_recorded_without_losing_failed_job(tmp_path):
    (tmp_path / "source.md").write_text("# 市场\n\n客观资料。", encoding="utf-8")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        result = _coordinator(
            db,
            tmp_path,
            BrokenIndexStore(),
            MarkdownDocumentParser(),
        ).ingest(_entry(), manifest_directory=tmp_path)
        version = db.scalar(select(KnowledgeDocumentVersion))
        job = db.scalar(select(KnowledgeIngestionJob))

    assert result.status == "failed"
    assert "index cleanup failed" in result.message
    assert version.index_status == "failed"
    assert job.status == "failed"


def _entry() -> KnowledgeManifestEntry:
    return KnowledgeManifestEntry(
        source=KnowledgeSourceInput(
            source_key="chengdu-test",
            title="成都餐饮测试资料",
            publisher="测试发布方",
            source_type="official_statistics",
            canonical_url="https://example.gov.cn/report",
            reliability_tier=1,
            default_city="成都",
            default_category="餐饮",
        ),
        acquisition=KnowledgeAcquisition(
            local_path="source.md",
            allowed_media_types=("text/markdown",),
        ),
        published_at=NOW,
        data_period_start=datetime(2025, 1, 1, tzinfo=UTC),
        data_period_end=datetime(2025, 12, 31, tzinfo=UTC),
        fact_status="observed",
        cities=("成都",),
        categories=("餐饮",),
    )


def _coordinator(db, root, index, parser):
    return KnowledgeIngestionCoordinator(
        db,
        loader=SecureDocumentLoader(),
        storage=KnowledgeStorage(root / "storage"),
        parser=parser,
        chunker=DeterministicKnowledgeChunker(),
        index_store=index,
        embedding_model="Qwen/Qwen3-Embedding-0.6B",
    )


def _persisted_source_and_version():
    source = SimpleNamespace(
        id=11,
        source_key="chengdu-test",
        title="成都餐饮测试资料",
        publisher="测试发布方",
        canonical_url="https://example.gov.cn/report",
        source_type="official_statistics",
        reliability_tier=1,
    )
    return source, SimpleNamespace(id=23)


class FailingParser:
    version = "failing-test-v1"

    def parse(self, _document, *, title):
        raise KnowledgeParseError(f"cannot parse {title}")


class BrokenIndexStore:
    def stage(self, _document_version_id, _chunks):
        raise TimeoutError("index unavailable")

    def count(self, _document_version_id):
        return 0

    def activate(self, _document_version_id, *, retire_version_ids):
        raise AssertionError("activation must not run")

    def discard(self, _document_version_id):
        raise TimeoutError("cleanup unavailable")
