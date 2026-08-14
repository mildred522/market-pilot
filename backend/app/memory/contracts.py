from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PublicMemoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)
    mode: str = Field(min_length=1, max_length=32)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
