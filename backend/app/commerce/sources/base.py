from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.commerce.contracts import CommerceCapability


class CommerceSourceAdapter(ABC):
    """Normalize one source into the platform-neutral commerce boundary."""

    source_type: str

    @property
    @abstractmethod
    def capabilities(self) -> frozenset[CommerceCapability]:
        raise NotImplementedError

    @abstractmethod
    def inspect(self, source: Any) -> dict[str, Any]:
        """Return a source quality summary without creating a snapshot."""
        raise NotImplementedError

    @abstractmethod
    def normalize(self, source: Any, *, snapshot_id: str) -> Any:
        """Normalize source records into canonical commerce records."""
        raise NotImplementedError
