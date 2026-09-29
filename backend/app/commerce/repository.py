from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.commerce.contracts import (
    CommerceAnalysisMode,
    CommerceBenchmarkSnapshotSummary,
)
from app.commerce.ingestion import CommerceDataset
from app.commerce.snapshot import CommerceSnapshot, SnapshotState
from app.db.models import CommerceBenchmarkSnapshot


class CommerceBenchmarkRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def save(self, dataset: CommerceDataset) -> CommerceDataset:
        snapshot = dataset.snapshot
        if (
            snapshot.mode is not CommerceAnalysisMode.BENCHMARK
            or snapshot.source_type != "public_dataset"
            or snapshot.state is not SnapshotState.READY
            or dataset.quality.blocking
        ):
            raise ValueError("only validated public benchmark snapshots can be persisted")

        existing = self._db.get(CommerceBenchmarkSnapshot, snapshot.snapshot_id)
        if existing is not None:
            return self._verify_existing(existing, dataset)

        self._db.add(
            CommerceBenchmarkSnapshot(
                snapshot_id=snapshot.snapshot_id,
                content_hash=snapshot.content_hash,
                dataset_json=dataset.model_dump(mode="json"),
            )
        )
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing = self._db.get(CommerceBenchmarkSnapshot, snapshot.snapshot_id)
            if existing is None:
                raise
            return self._verify_existing(existing, dataset)
        return dataset

    def get(self, snapshot_id: str) -> CommerceDataset | None:
        record = self._db.get(CommerceBenchmarkSnapshot, snapshot_id)
        if record is None:
            return None
        dataset = CommerceDataset.model_validate(record.dataset_json)
        if (
            dataset.snapshot.snapshot_id != record.snapshot_id
            or dataset.snapshot.content_hash != record.content_hash
            or dataset.snapshot.mode is not CommerceAnalysisMode.BENCHMARK
            or dataset.snapshot.source_type != "public_dataset"
            or dataset.snapshot.state is not SnapshotState.READY
            or dataset.quality.blocking
        ):
            raise ValueError("persisted commerce benchmark snapshot metadata is inconsistent")
        return dataset

    def list(self) -> tuple[CommerceBenchmarkSnapshotSummary, ...]:
        records = self._db.scalars(
            select(CommerceBenchmarkSnapshot).order_by(
                CommerceBenchmarkSnapshot.created_at.desc(),
                CommerceBenchmarkSnapshot.snapshot_id.asc(),
            )
        ).all()
        summaries = [self._summary(record) for record in records]
        return tuple(
            sorted(
                summaries,
                key=lambda summary: (summary.created_at, summary.snapshot_id),
                reverse=True,
            )
        )

    def _verify_existing(
        self, existing: CommerceBenchmarkSnapshot, candidate: CommerceDataset
    ) -> CommerceDataset:
        saved = self.get(existing.snapshot_id)
        if (
            saved is None
            or saved.snapshot.content_hash != candidate.snapshot.content_hash
            or saved.snapshot.schema_version != candidate.snapshot.schema_version
            or saved.snapshot.capabilities != candidate.snapshot.capabilities
            or saved.products != candidate.products
            or saved.skus != candidate.skus
            or saved.orders != candidate.orders
            or saved.order_items != candidate.order_items
            or saved.quality != candidate.quality
        ):
            raise ValueError("snapshot id already exists with different dataset content")
        return saved

    @staticmethod
    def _summary(
        record: CommerceBenchmarkSnapshot,
    ) -> CommerceBenchmarkSnapshotSummary:
        snapshot_payload = record.dataset_json.get("snapshot")
        if not isinstance(snapshot_payload, dict):
            raise ValueError("persisted commerce benchmark snapshot metadata is inconsistent")
        metadata = CommerceSnapshot.model_validate(snapshot_payload)
        if (
            metadata.snapshot_id != record.snapshot_id
            or metadata.content_hash != record.content_hash
            or metadata.mode is not CommerceAnalysisMode.BENCHMARK
            or metadata.source_type != "public_dataset"
            or metadata.state is not SnapshotState.READY
        ):
            raise ValueError("persisted commerce benchmark snapshot metadata is inconsistent")
        return CommerceBenchmarkSnapshotSummary(
            snapshot_id=metadata.snapshot_id,
            source_type=metadata.source_type,
            schema_version=metadata.schema_version,
            content_hash=metadata.content_hash,
            created_at=metadata.created_at,
            period_start=metadata.period_start,
            period_end=metadata.period_end,
            timezone=metadata.timezone,
            capabilities=tuple(sorted(metadata.capabilities, key=lambda value: value.value)),
            row_counts=dict(metadata.row_counts),
        )
