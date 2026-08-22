from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    KnowledgeDocumentVersion,
    KnowledgeFact,
    KnowledgeIngestionJob,
    KnowledgeSource,
)
from app.knowledge.contracts import (
    KnowledgeDocumentVersionInput,
    KnowledgeFactInput,
    KnowledgeSourceInput,
)


class KnowledgeSourceRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_source(self, source_key: str) -> KnowledgeSource | None:
        return self._db.scalar(
            select(KnowledgeSource).where(KnowledgeSource.source_key == source_key)
        )

    def upsert_source(self, value: KnowledgeSourceInput) -> KnowledgeSource:
        source = self.get_source(value.source_key)
        payload = value.model_dump(mode="json")
        payload["canonical_url"] = str(value.canonical_url)
        if source is None:
            source = KnowledgeSource(**payload)
            self._db.add(source)
        else:
            for key, item in payload.items():
                setattr(source, key, item)
        self._db.flush()
        return source

    def register_version(
        self,
        source_id: int,
        value: KnowledgeDocumentVersionInput,
    ) -> tuple[KnowledgeDocumentVersion, bool]:
        existing = self._db.scalar(
            select(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.source_id == source_id,
                KnowledgeDocumentVersion.content_hash == value.content_hash,
            )
        )
        if existing is not None:
            return existing, False
        next_version = (
            self._db.scalar(
                select(func.max(KnowledgeDocumentVersion.version_number)).where(
                    KnowledgeDocumentVersion.source_id == source_id
                )
            )
            or 0
        ) + 1
        version = KnowledgeDocumentVersion(
            source_id=source_id,
            version_number=next_version,
            index_status="pending",
            **value.model_dump(),
        )
        self._db.add(version)
        self._db.flush()
        return version, True

    def active_version(self, source_id: int) -> KnowledgeDocumentVersion | None:
        return self._db.scalar(
            select(KnowledgeDocumentVersion)
            .where(
                KnowledgeDocumentVersion.source_id == source_id,
                KnowledgeDocumentVersion.index_status == "active",
            )
            .order_by(KnowledgeDocumentVersion.version_number.desc())
            .limit(1)
        )

    def activate_version(
        self,
        version: KnowledgeDocumentVersion,
        *,
        indexed_at: datetime,
    ) -> list[int]:
        previous = list(
            self._db.scalars(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.source_id == version.source_id,
                    KnowledgeDocumentVersion.index_status == "active",
                    KnowledgeDocumentVersion.id != version.id,
                )
            )
        )
        for item in previous:
            item.index_status = "retired"
        version.index_status = "active"
        version.indexed_at = indexed_at
        self._db.flush()
        return [item.id for item in previous]

    def fail_version(self, version: KnowledgeDocumentVersion) -> None:
        if version.index_status == "active":
            previous = self._db.scalar(
                select(KnowledgeDocumentVersion)
                .where(
                    KnowledgeDocumentVersion.source_id == version.source_id,
                    KnowledgeDocumentVersion.index_status == "retired",
                )
                .order_by(KnowledgeDocumentVersion.version_number.desc())
                .limit(1)
            )
            if previous is not None:
                previous.index_status = "active"
        version.index_status = "failed"
        self._db.flush()

    def add_fact(
        self,
        document_version_id: int,
        value: KnowledgeFactInput,
    ) -> KnowledgeFact:
        payload = value.model_dump()
        payload["value_json"] = payload.pop("value")
        fact = KnowledgeFact(document_version_id=document_version_id, **payload)
        self._db.add(fact)
        self._db.flush()
        return fact

    def start_job(self, document_version_id: int) -> KnowledgeIngestionJob:
        job = KnowledgeIngestionJob(
            document_version_id=document_version_id,
            status="running",
            stage="registered",
        )
        self._db.add(job)
        self._db.flush()
        return job

    def finish_job(
        self,
        job: KnowledgeIngestionJob,
        *,
        status: str,
        stage: str,
        chunks_parsed: int,
        chunks_indexed: int,
        finished_at: datetime,
        error_code: str | None = None,
    ) -> KnowledgeIngestionJob:
        job.status = status
        job.stage = stage
        job.chunks_parsed = chunks_parsed
        job.chunks_indexed = chunks_indexed
        job.finished_at = finished_at
        job.error_code = error_code
        self._db.flush()
        return job
