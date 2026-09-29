from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.commerce.contracts import CommerceAnalysisMode, CommerceCapability


class SnapshotState(StrEnum):
    READY = "ready"
    FAILED = "failed"


class CommerceSnapshot(BaseModel):
    """Immutable metadata for one normalized commerce data version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1, max_length=120)
    mode: CommerceAnalysisMode
    source_type: str = Field(min_length=1, max_length=120)
    schema_version: str = Field(min_length=1, max_length=40)
    content_hash: str = Field(min_length=1, max_length=128)
    created_at: datetime
    period_start: datetime | None = None
    period_end: datetime | None = None
    timezone: str | None = Field(default=None, max_length=80)
    capabilities: frozenset[CommerceCapability] = frozenset()
    row_counts: dict[str, int] = Field(default_factory=dict)
    state: SnapshotState = SnapshotState.READY

    @model_validator(mode="after")
    def validate_period(self) -> "CommerceSnapshot":
        if (
            self.period_start is not None
            and self.period_end is not None
            and self.period_end < self.period_start
        ):
            raise ValueError("snapshot period_end must be after period_start")
        if any(count < 0 for count in self.row_counts.values()):
            raise ValueError("snapshot row counts cannot be negative")
        return self
