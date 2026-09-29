from __future__ import annotations

from threading import RLock

from app.commerce.ingestion import CommerceDataset


class CommerceDatasetRegistry:
    """Process-local registry for immutable datasets used by the first API slice.

    This registry intentionally does not provide persistence or a public upload
    endpoint. A later storage-backed implementation can preserve this interface
    while moving snapshots out of process memory.
    """

    def __init__(self) -> None:
        self._datasets: dict[str, CommerceDataset] = {}
        self._lock = RLock()

    def register(self, dataset: CommerceDataset) -> CommerceDataset:
        snapshot_id = dataset.snapshot.snapshot_id
        with self._lock:
            existing = self._datasets.get(snapshot_id)
            if existing is not None and (
                existing.snapshot.content_hash != dataset.snapshot.content_hash
            ):
                raise ValueError(f"snapshot id already exists with different content: {snapshot_id}")
            self._datasets[snapshot_id] = dataset
        return dataset

    def get(self, snapshot_id: str) -> CommerceDataset | None:
        with self._lock:
            return self._datasets.get(snapshot_id)

    def remove(self, snapshot_id: str) -> CommerceDataset | None:
        with self._lock:
            return self._datasets.pop(snapshot_id, None)

    def clear(self) -> None:
        with self._lock:
            self._datasets.clear()


commerce_dataset_registry = CommerceDatasetRegistry()
