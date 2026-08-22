from __future__ import annotations

from typing import Protocol

from app.knowledge.document import KnowledgeChunk


class KnowledgeIndexStore(Protocol):
    def stage(
        self,
        document_version_id: int,
        chunks: tuple[KnowledgeChunk, ...],
    ) -> None: ...

    def count(self, document_version_id: int) -> int: ...

    def activate(
        self,
        document_version_id: int,
        *,
        retire_version_ids: tuple[int, ...],
    ) -> None: ...

    def discard(self, document_version_id: int) -> None: ...


class InMemoryKnowledgeIndexStore:
    """Deterministic test/demo index with the same staging contract as Qdrant."""

    def __init__(self) -> None:
        self.points: dict[str, KnowledgeChunk] = {}
        self.version_status: dict[int, str] = {}
        self._retired_by_activation: dict[int, tuple[int, ...]] = {}

    def stage(
        self,
        document_version_id: int,
        chunks: tuple[KnowledgeChunk, ...],
    ) -> None:
        for chunk in chunks:
            if chunk.document_version_id != document_version_id:
                raise ValueError(
                    "chunk document version does not match staging version"
                )
            self.points[chunk.point_id] = chunk
        self.version_status[document_version_id] = "staging"

    def count(self, document_version_id: int) -> int:
        return sum(
            chunk.document_version_id == document_version_id
            for chunk in self.points.values()
        )

    def activate(
        self,
        document_version_id: int,
        *,
        retire_version_ids: tuple[int, ...],
    ) -> None:
        if self.version_status.get(document_version_id) != "staging":
            raise ValueError("only a staged document version can be activated")
        self.version_status[document_version_id] = "active"
        self._retired_by_activation[document_version_id] = retire_version_ids
        for version_id in retire_version_ids:
            if version_id in self.version_status:
                self.version_status[version_id] = "retired"

    def discard(self, document_version_id: int) -> None:
        self.points = {
            point_id: chunk
            for point_id, chunk in self.points.items()
            if chunk.document_version_id != document_version_id
        }
        self.version_status.pop(document_version_id, None)
        for version_id in self._retired_by_activation.pop(document_version_id, ()):
            self.version_status[version_id] = "active"
