from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


CoordinateSystem = Literal["bd09ll"]


class FinanceAssumptions(BaseModel):
    gross_margin: float | None = Field(default=None, ge=0, le=1)
    labor_cost: float | None = Field(default=None, ge=0)
    utilities_cost: float | None = Field(default=None, ge=0)
    other_fixed_cost: float | None = Field(default=None, ge=0)
    target_daily_orders: int | None = Field(default=None, ge=0)
    monthly_rent: float | None = Field(default=None, ge=0)


class LocationRequestBase(BaseModel):
    project_id: int = Field(gt=0)
    city: str = Field(min_length=1, max_length=80)
    district: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=80)
    target_customer: str = Field(min_length=1, max_length=200)
    planned_average_order_value: float = Field(gt=0, allow_inf_nan=False)
    finance_assumptions: FinanceAssumptions | None = None
    coordinate_system: CoordinateSystem = "bd09ll"


class ManualLocationAnalysisRequest(LocationRequestBase):
    address: str | None = Field(default=None, min_length=1, max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

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
    candidate_count: int = Field(default=5, ge=3, le=5)
    radius_meters: int = Field(default=1500, ge=300, le=5000)


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
