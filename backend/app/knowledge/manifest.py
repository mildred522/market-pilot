from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.knowledge.contracts import KnowledgeFactStatus, KnowledgeSourceInput


class KnowledgeAcquisition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: HttpUrl | None = None
    local_path: str | None = Field(default=None, max_length=500)
    expected_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-fA-F0-9]{64}$",
    )
    allowed_media_types: tuple[str, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_single_location(self) -> KnowledgeAcquisition:
        if (self.url is None) == (self.local_path is None):
            raise ValueError("exactly one of url or local_path is required")
        if self.local_path is not None:
            path = Path(self.local_path)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("local_path must stay relative to the manifest")
        return self


class KnowledgeManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: KnowledgeSourceInput
    acquisition: KnowledgeAcquisition
    published_at: datetime | None = None
    data_period_start: datetime | None = None
    data_period_end: datetime | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    fact_status: KnowledgeFactStatus
    cities: tuple[str, ...] = Field(default_factory=tuple, max_length=20)
    categories: tuple[str, ...] = Field(default_factory=tuple, max_length=20)

    @model_validator(mode="after")
    def validate_periods(self) -> KnowledgeManifestEntry:
        if (
            self.data_period_start is not None
            and self.data_period_end is not None
            and self.data_period_start > self.data_period_end
        ):
            raise ValueError("data_period_start must not exceed data_period_end")
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_from > self.effective_to
        ):
            raise ValueError("effective_from must not exceed effective_to")
        return self


class KnowledgeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_version: int = Field(default=1, ge=1, le=1)
    documents: tuple[KnowledgeManifestEntry, ...] = Field(
        min_length=1,
        max_length=500,
    )

    @model_validator(mode="after")
    def validate_unique_source_keys(self) -> KnowledgeManifest:
        keys = [document.source.source_key for document in self.documents]
        if len(keys) != len(set(keys)):
            raise ValueError("manifest source_key values must be unique")
        return self


def load_knowledge_manifest(path: Path) -> KnowledgeManifest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return KnowledgeManifest.model_validate(payload)
