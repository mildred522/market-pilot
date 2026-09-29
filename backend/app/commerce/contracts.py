from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CommerceAnalysisMode(StrEnum):
    MERCHANT = "merchant"
    BENCHMARK = "benchmark"


class InteractionMode(StrEnum):
    TALK = "talk"
    PLAN = "plan"


class CommerceCapability(StrEnum):
    CATALOG = "catalog"
    SALES = "sales"
    REVIEWS = "reviews"
    COSTS = "costs"
    INVENTORY = "inventory"
    RETURNS = "returns"
    TRAFFIC = "traffic"
    CAMPAIGNS = "campaigns"


class CommerceScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: CommerceAnalysisMode
    project_id: int
    store_id: int | None = None
    snapshot_id: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_scope(self) -> "CommerceScope":
        if self.mode is CommerceAnalysisMode.MERCHANT and self.store_id is None:
            raise ValueError("merchant analysis requires store_id")
        return self


class CapabilityAvailability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: CommerceCapability
    status: Literal["supported", "partial", "unsupported"]
    missing: tuple[CommerceCapability, ...] = ()
    reason: str | None = Field(default=None, max_length=300)


class CommerceInteraction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: InteractionMode
    scope: CommerceScope
    requested_capabilities: tuple[CommerceCapability, ...] = ()
