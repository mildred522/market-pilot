from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class EvidenceRecord(BaseModel):
    source: str
    label: str
    observed_at: datetime
    expires_at: datetime
    scope: dict[str, Any] = Field(default_factory=dict)
    value: Any


class ExternalContextData(BaseModel):
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ReferenceSource(BaseModel):
    source_id: str
    title: str
    publisher: str
    url: HttpUrl
    published_at: datetime
    accessed_at: date
    source_type: Literal[
        "government_statistics",
        "industry_association",
        "listed_company_filing",
        "commercial_research",
    ]
    notes: str | None = None


class ReferenceMetric(BaseModel):
    value: int | float
    unit: str
    period: str
    source_ids: list[str] = Field(min_length=1)
    status: Literal["reported", "estimated", "forecast", "derived"]
    definition: str | None = None
    qualifier: Literal["exact", "about", "more_than", "less_than"] = "exact"


class ReferenceDataset(BaseModel):
    dataset_id: str
    effective_year: int
    published_at: datetime
    sources: list[ReferenceSource] = Field(min_length=1)
    metrics: dict[str, ReferenceMetric]
    observations: list[str]
    limitations: list[str]

    @model_validator(mode="after")
    def validate_metric_sources(self) -> "ReferenceDataset":
        source_ids = {source.source_id for source in self.sources}
        unknown = {
            source_id
            for metric in self.metrics.values()
            for source_id in metric.source_ids
            if source_id not in source_ids
        }
        if unknown:
            raise ValueError(f"unknown source ids: {sorted(unknown)}")
        return self


class BaiduPoi(BaseModel):
    uid: str
    name: str
    latitude: float
    longitude: float
    address: str = ""
    business_status: str = ""
    distance_meters: int | None = None
    tag: str | None = None
    brand: str | None = None
    rating: float | None = None
    comment_count: int | None = None
    average_price: float | None = None


class BaiduRouteMatrixItem(BaseModel):
    distance_meters: int = Field(ge=0)
    duration_seconds: int = Field(ge=0)


class BaiduRouteMatrixResult(BaseModel):
    mode: Literal["driving", "riding", "walking"]
    routes: list[BaiduRouteMatrixItem]


class BaiduPoiSearchResult(BaseModel):
    query: str
    center_latitude: float | None = None
    center_longitude: float | None = None
    coordinate_system: Literal["bd09ll"] = "bd09ll"
    radius_meters: int | None = None
    region: str | None = None
    page_num: int = Field(default=0, ge=0)
    page_size: int = Field(default=20, ge=1, le=20)
    total: int
    pois: list[BaiduPoi]
    pagination_supported: bool = True
    provider: Literal["baidu_webapi", "baidu_mcp"] = "baidu_webapi"
    provider_warning: str | None = None
