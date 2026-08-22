from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AcquiredDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: bytes
    media_type: str = Field(min_length=1, max_length=120)
    filename: str = Field(min_length=1, max_length=300)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ParsedBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["paragraph", "list_item", "table", "caption"]
    text: str = Field(min_length=1)
    heading_path: tuple[str, ...] = Field(default_factory=tuple, max_length=12)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)


class ParsedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=300)
    blocks: tuple[ParsedBlock, ...] = Field(min_length=1)


class KnowledgeChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    point_id: str = Field(min_length=36, max_length=36)
    chunk_id: str = Field(min_length=1, max_length=80)
    document_version_id: int = Field(gt=0)
    chunk_index: int = Field(ge=0)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    raw_text: str = Field(min_length=1)
    retrieval_text: str = Field(min_length=1)
    heading_path: tuple[str, ...] = Field(default_factory=tuple)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    payload: dict[str, object]
