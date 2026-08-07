from typing import Any, Literal

from pydantic import BaseModel, Field, StrictFloat, StrictInt, model_validator


CoordinateSystem = Literal["bd09ll"]


class FinanceAssumptions(BaseModel):
    gross_margin: StrictFloat | None = Field(default=None, ge=0, le=1)
    labor_cost: StrictFloat | None = Field(default=None, ge=0, allow_inf_nan=False)
    utilities_cost: StrictFloat | None = Field(default=None, ge=0, allow_inf_nan=False)
    other_fixed_cost: StrictFloat | None = Field(default=None, ge=0, allow_inf_nan=False)
    target_daily_orders: StrictInt | None = Field(default=None, ge=0)
    monthly_rent: StrictFloat | None = Field(default=None, ge=0, allow_inf_nan=False)


class LocationRequestBase(BaseModel):
    project_id: StrictInt = Field(gt=0)
    city: str = Field(min_length=1, max_length=80)
    district: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=80)
    target_customer: str = Field(min_length=1, max_length=200)
    planned_average_order_value: StrictFloat = Field(gt=0, allow_inf_nan=False)
    finance_assumptions: FinanceAssumptions | None = None
    coordinate_system: CoordinateSystem = "bd09ll"
    radius_meters: StrictInt = Field(default=1500, ge=300, le=5000)


class ManualLocationAnalysisRequest(LocationRequestBase):
    address: str | None = Field(default=None, min_length=1, max_length=500)
    latitude: StrictFloat | None = Field(default=None, ge=-90, le=90)
    longitude: StrictFloat | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def require_exactly_one_location(self) -> "ManualLocationAnalysisRequest":
        has_address = self.address is not None
        has_coordinates = self.latitude is not None and self.longitude is not None
        if has_address == has_coordinates:
            raise ValueError(
                "provide exactly one complete location: address or latitude+longitude"
            )
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class LocationRecommendationsRequest(LocationRequestBase):
    candidate_count: StrictInt = Field(default=5, ge=1, le=10)


class Coordinate(BaseModel):
    latitude: float
    longitude: float
    coordinate_system: CoordinateSystem = "bd09ll"
    source: str | None = None


class OpportunitySummary(BaseModel):
    score: float | None = None
    conclusion: str | None = None


class ConfidenceSummary(BaseModel):
    score: float | None = None


class FinanceSummary(BaseModel):
    feasibility: str | None = None
    assumptions_provided: bool = False
    metrics: dict[str, Any] = Field(default_factory=dict)
    disclaimer: str = "This is a planning assumption, not observed rent or revenue."


class RecommendationCandidate(BaseModel):
    name: str
    center: Coordinate
    transition_coordinates: Coordinate
    opportunity: OpportunitySummary
    confidence: ConfidenceSummary
    finance: FinanceSummary
    dimension_breakdown: dict[str, Any] = Field(default_factory=dict)
    confidence_breakdown: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class LocationAnalysisResponse(BaseModel):
    mode: str
    status: str
    analysis_id: int
    input_scope: dict[str, Any] = Field(default_factory=dict)
    center: Coordinate | None = None
    opportunity: OpportunitySummary
    confidence: ConfidenceSummary
    finance: FinanceSummary
    dimension_breakdown: dict[str, Any] = Field(default_factory=dict)
    confidence_breakdown: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    transition_coordinates: Coordinate | None = None
    candidates: list[RecommendationCandidate] = Field(default_factory=list)


ManualLocationAnalysisResponse = LocationAnalysisResponse
