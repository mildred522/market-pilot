from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.knowledge.admission import KnowledgeAdmissionPolicy
from app.knowledge.chunker import DeterministicKnowledgeChunker
from app.knowledge.contracts import KnowledgeDocumentVersionInput
from app.knowledge.document import AcquiredDocument
from app.knowledge.fact_extractor import DeterministicKnowledgeFactExtractor
from app.knowledge.index_store import KnowledgeIndexStore
from app.knowledge.manifest import KnowledgeManifestEntry
from app.knowledge.parser import DocumentParser
from app.knowledge.source_repository import KnowledgeSourceRepository
from app.knowledge.storage import KnowledgeStorage


class DocumentLoader(Protocol):
    def acquire(
        self,
        entry: KnowledgeManifestEntry,
        *,
        manifest_directory: Path,
    ) -> AcquiredDocument: ...


class KnowledgeIngestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_key: str
    status: str
    document_version_id: int | None = None
    chunks_indexed: int = 0
    facts_extracted: int = 0
    error_code: str | None = None
    message: str | None = None
    admission_route: str | None = None
    admission_warnings: tuple[str, ...] = ()


class KnowledgeIngestionCoordinator:
    def __init__(
        self,
        db: Session,
        *,
        loader: DocumentLoader,
        storage: KnowledgeStorage,
        parser: DocumentParser,
        chunker: DeterministicKnowledgeChunker,
        index_store: KnowledgeIndexStore,
        embedding_model: str,
        admission_policy: KnowledgeAdmissionPolicy | None = None,
        fact_extractor: DeterministicKnowledgeFactExtractor | None = None,
    ) -> None:
        self._db = db
        self._loader = loader
        self._storage = storage
        self._parser = parser
        self._chunker = chunker
        self._index = index_store
        self._embedding_model = embedding_model
        self._admission = admission_policy or KnowledgeAdmissionPolicy()
        self._fact_extractor = fact_extractor or DeterministicKnowledgeFactExtractor()
        self._repository = KnowledgeSourceRepository(db)

    def ingest(
        self,
        entry: KnowledgeManifestEntry,
        *,
        manifest_directory: Path,
    ) -> KnowledgeIngestionResult:
        source_decision = self._admission.classify(entry)
        if not source_decision.accepted_for_qdrant:
            return KnowledgeIngestionResult(
                source_key=entry.source.source_key,
                status="rejected",
                error_code=source_decision.reason_codes[0],
                message="source route is not eligible for Qdrant indexing",
                admission_route=source_decision.route,
                admission_warnings=source_decision.warnings,
            )
        version = None
        job = None
        chunks_indexed = 0
        try:
            acquired = self._loader.acquire(
                entry,
                manifest_directory=manifest_directory,
            )
            raw_path = self._storage.store_raw(
                source_key=entry.source.source_key,
                document=acquired,
            )
            source = self._repository.upsert_source(entry.source)
            build_hash = _document_build_hash(
                acquired.sha256,
                parser_version=self._parser.version,
                chunker_version=self._chunker.version,
                embedding_model=self._embedding_model,
            )
            version, created = self._repository.register_version(
                source.id,
                KnowledgeDocumentVersionInput(
                    content_hash=build_hash,
                    published_at=entry.published_at,
                    data_period_start=entry.data_period_start,
                    data_period_end=entry.data_period_end,
                    effective_from=entry.effective_from,
                    effective_to=entry.effective_to,
                    fact_status=entry.fact_status,
                    raw_storage_path=raw_path,
                    media_type=acquired.media_type,
                    parser_version=self._parser.version,
                    chunker_version=self._chunker.version,
                    embedding_model=self._embedding_model,
                ),
            )
            if not created and version.index_status == "active":
                if self._fact_extractor.review_status == "approved":
                    self._repository.approve_pending_facts(version.id)
                self._db.commit()
                return KnowledgeIngestionResult(
                    source_key=entry.source.source_key,
                    status="unchanged",
                    document_version_id=version.id,
                    chunks_indexed=self._index.count(version.id),
                    facts_extracted=self._repository.count_facts(version.id),
                    admission_route=source_decision.route,
                )

            version.index_status = "indexing"
            job = self._repository.start_job(version.id)
            parsed = self._parser.parse(acquired, title=entry.source.title)
            admission = self._admission.assess(entry, acquired, parsed)
            if not admission.accepted_for_qdrant:
                now = datetime.now(UTC)
                self._repository.fail_version(version)
                self._repository.finish_job(
                    job,
                    status="failed",
                    stage="admission_rejected",
                    chunks_parsed=0,
                    chunks_indexed=0,
                    finished_at=now,
                    error_code=admission.reason_codes[0],
                )
                self._db.commit()
                return KnowledgeIngestionResult(
                    source_key=entry.source.source_key,
                    status="rejected",
                    document_version_id=version.id,
                    error_code=admission.reason_codes[0],
                    message=", ".join(admission.reason_codes),
                    admission_route=admission.route,
                    admission_warnings=admission.warnings,
                )
            chunks = self._chunker.chunk(
                parsed,
                entry=entry,
                source=source,
                version=version,
            )
            facts = (
                self._fact_extractor.extract(chunks, entry=entry)
                if admission.extract_structured_facts
                else ()
            )
            if not chunks:
                raise ValueError("parser produced no chunks")
            job.stage = "indexing"
            job.chunks_parsed = len(chunks)
            self._index.stage(version.id, chunks)
            chunks_indexed = self._index.count(version.id)
            if chunks_indexed != len(chunks):
                raise ValueError("staged index count does not match parsed chunks")

            self._repository.replace_facts(version.id, facts)

            previous = self._repository.active_version(source.id)
            retire_ids = (previous.id,) if previous is not None else ()
            self._index.activate(
                version.id,
                retire_version_ids=retire_ids,
            )
            now = datetime.now(UTC)
            self._repository.activate_version(version, indexed_at=now)
            self._repository.finish_job(
                job,
                status="completed",
                stage="activated",
                chunks_parsed=len(chunks),
                chunks_indexed=chunks_indexed,
                finished_at=now,
            )
            self._db.commit()
            return KnowledgeIngestionResult(
                source_key=entry.source.source_key,
                status="ingested",
                document_version_id=version.id,
                chunks_indexed=chunks_indexed,
                facts_extracted=len(facts),
                admission_route=admission.route,
                admission_warnings=admission.warnings,
            )
        except Exception as error:
            cleanup_error = None
            if version is not None and version.id is not None:
                try:
                    self._index.discard(version.id)
                except Exception as cleanup_failure:
                    cleanup_error = type(cleanup_failure).__name__
                self._repository.fail_version(version)
            if job is not None:
                self._repository.finish_job(
                    job,
                    status="failed",
                    stage="failed",
                    chunks_parsed=job.chunks_parsed,
                    chunks_indexed=chunks_indexed,
                    finished_at=datetime.now(UTC),
                    error_code=_error_code(error),
                )
            self._db.commit()
            return KnowledgeIngestionResult(
                source_key=entry.source.source_key,
                status="failed",
                document_version_id=version.id if version is not None else None,
                chunks_indexed=chunks_indexed,
                error_code=_error_code(error),
                message=(
                    f"{error}; index cleanup failed: {cleanup_error}"
                    if cleanup_error
                    else str(error)
                ),
            )


def _error_code(error: Exception) -> str:
    name = type(error).__name__
    return "".join(
        f"_{character.lower()}" if character.isupper() else character
        for character in name
    ).lstrip("_")[:80]


def _document_build_hash(
    raw_sha256: str,
    *,
    parser_version: str,
    chunker_version: str,
    embedding_model: str,
) -> str:
    identity = "\n".join(
        (raw_sha256, parser_version, chunker_version, embedding_model)
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()
