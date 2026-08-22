from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

KnowledgeSourceStatus = Literal["active", "inactive"]
KnowledgeFactStatus = Literal["observed", "forecast", "mixed"]
KnowledgeIndexStatus = Literal["pending", "indexing", "active", "failed", "retired"]
KnowledgeReviewStatus = Literal["pending", "approved", "rejected"]
KnowledgeJobStatus = Literal["pending", "running", "completed", "failed"]


class KnowledgeSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_key: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    title: str = Field(min_length=1, max_length=300)
    publisher: str = Field(min_length=1, max_length=200)
    source_type: str = Field(min_length=1, max_length=48)
    canonical_url: HttpUrl
    reliability_tier: int = Field(ge=1, le=4)
    default_city: str | None = Field(default=None, max_length=80)
    default_category: str | None = Field(default=None, max_length=80)
    status: KnowledgeSourceStatus = "active"


class KnowledgeDocumentVersionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content_hash: str = Field(min_length=8, max_length=80)
    published_at: datetime | None = None
    data_period_start: datetime | None = None
    data_period_end: datetime | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    fact_status: KnowledgeFactStatus
    raw_storage_path: str = Field(min_length=1, max_length=500)
    media_type: str = Field(min_length=1, max_length=120)
    parser_version: str = Field(min_length=1, max_length=80)
    chunker_version: str = Field(min_length=1, max_length=80)
    embedding_model: str = Field(min_length=1, max_length=160)


class KnowledgeFactInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_key: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=240)
    value: Any
    unit: str = Field(default="none", max_length=80)
    geography: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=120)
    observed_or_forecast: Literal["observed", "forecast"]
    source_chunk_id: str | None = Field(default=None, max_length=160)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    review_status: KnowledgeReviewStatus = "pending"


class KnowledgeRagSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str = ""
    collection: str = "market_pilot_knowledge_v1"
    storage_root: str = "./storage/knowledge"
    dense_model: str = "Qwen/Qwen3-Embedding-0.6B"
    reranker_model: str = "Qwen/Qwen3-Reranker-0.6B"
    rerank_enabled: bool = True
    retrieval_timeout_seconds: float = Field(default=8.0, gt=0, le=60)

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.qdrant_url.strip())


class KnowledgeServiceHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["disabled", "unavailable", "ready", "degraded"]
    enabled: bool
    configured: bool
    degradations: tuple[str, ...] = ()
