from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.commerce.contracts import CommerceAnalysisMode
from app.commerce.ingestion import CommerceDataset
from app.commerce.snapshot import SnapshotState
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
