from datetime import datetime
from enum import Enum
from math import isclose
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class PoiClassification(str, Enum):
    DIRECT_COMPETITOR = "direct_competitor"
    SUBSTITUTE = "substitute"
    DEMAND_PROXY = "demand_proxy"
    TRANSIT = "transit"
    AMENITY = "amenity"


class FinanceFeasibility(str, Enum):
    FEASIBLE = "feasible"
    ADJUSTABLE = "adjustable"
    INFEASIBLE = "infeasible"
    MISSING = "missing"


class NormalizedPoiFeature(BaseModel):
    uid: str
    name: str
    distance_meters: int | None = Field(default=None, ge=0)
    matched_keywords: list[str] = Field(default_factory=list)
    category: str | None = None
    classifications: list[PoiClassification] = Field(default_factory=list)
    average_price: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )
    business_status: str | None = None
    comment_count: int | None = Field(default=None, ge=0)


class RingMetrics(BaseModel):
    radius_meters: int = Field(ge=0)
    direct_competitors: int = Field(default=0, ge=0)
    substitutes: int = Field(default=0, ge=0)
    demand_proxies: int = Field(default=0, ge=0)
    transit: int = Field(default=0, ge=0)
    amenities: int = Field(default=0, ge=0)


class PriceMetrics(BaseModel):
    eligible_count: int = Field(default=0, ge=0)
    sample_count: int = Field(default=0, ge=0)
    coverage: float = Field(default=0, ge=0, le=1)
    median: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    first_quartile: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )
    third_quartile: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )
    minimum: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    maximum: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_invariants(self) -> "PriceMetrics":
        if self.sample_count > self.eligible_count:
            raise ValueError("sample_count cannot exceed eligible_count")

        expected_coverage = (
            self.sample_count / self.eligible_count
            if self.eligible_count
            else 0
        )
        if not isclose(
            self.coverage,
            expected_coverage,
            rel_tol=0,
            abs_tol=1e-4,
        ):
            raise ValueError("coverage must match sampled price coverage")

        distribution = [
            self.minimum,
            self.first_quartile,
            self.median,
            self.third_quartile,
            self.maximum,
        ]
        has_distribution = any(value is not None for value in distribution)
        if has_distribution and self.sample_count == 0:
            raise ValueError("distribution requires a positive sample_count")
        if has_distribution:
            if any(value is None for value in distribution):
                raise ValueError("all distribution fields must be provided together")
            values = [float(value) for value in distribution if value is not None]
            if values != sorted(values):
                raise ValueError("distribution fields must be ordered")
        return self


class LocationFeatures(BaseModel):
    pois: list[NormalizedPoiFeature]
    rings: dict[int, RingMetrics]
    price: PriceMetrics


class DimensionScores(BaseModel):
    competition_balance: float = Field(ge=0, le=100)
    demand_proxies: float = Field(ge=0, le=100)
    transit: float = Field(ge=0, le=100)
    price_fit: float = Field(ge=0, le=100)
    surrounding_synergy: float = Field(ge=0, le=100)


class OpportunityWeights(BaseModel):
    competition_balance: int = Field(default=25, ge=0)
    demand_proxies: int = Field(default=25, ge=0)
    transit: int = Field(default=20, ge=0)
    price_fit: int = Field(default=15, ge=0)
    surrounding_synergy: int = Field(default=15, ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> "OpportunityWeights":
        if sum(self.model_dump().values()) != 100:
            raise ValueError("opportunity weights must total 100")
        return self


class DimensionScoreBreakdown(DimensionScores):
    competition_weighted: float
    demand_weighted: float
    transit_weighted: float
    price_weighted: float
    synergy_weighted: float


class ConfidenceInputs(BaseModel):
    pagination: float = Field(ge=0, le=1)
    key_fields: float = Field(ge=0, le=1)
    keyword_coverage: float = Field(ge=0, le=1)
    freshness: float = Field(ge=0, le=1)
    status_comment_coverage: float = Field(ge=0, le=1)


class ConfidenceComponent(BaseModel):
    raw_coverage: float = Field(ge=0, le=1)
    weight: int = Field(ge=0)
    weighted_score: float = Field(ge=0)


class ConfidenceBreakdown(BaseModel):
    pagination: ConfidenceComponent
    key_fields: ConfidenceComponent
    keyword_coverage: ConfidenceComponent
    freshness: ConfidenceComponent
    status_comment_coverage: ConfidenceComponent


class Evidence(BaseModel):
    source: str
    label: str
    observed_at: datetime
    expires_at: datetime
    query_scope: dict[str, Any] = Field(default_factory=dict)
    value: Any


Conclusion = Literal["建议开", "调整后再开", "不建议开", "继续调研"]


class LocationAnalysisResult(BaseModel):
    opportunity_score: float = Field(ge=0, le=100)
    confidence_score: float = Field(ge=0, le=100)
    finance_feasibility: FinanceFeasibility
    conclusion: Conclusion
    dimension_scores: DimensionScoreBreakdown
    confidence: ConfidenceBreakdown
    finance_metrics: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
