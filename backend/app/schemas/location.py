from typing import Any, Literal

from math import isfinite

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator, model_validator


CoordinateSystem = Literal["bd09ll"]


class FinanceAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gross_margin: StrictFloat | None = Field(default=None, ge=0, le=1)
    labor_cost: StrictFloat | None = Field(default=None, ge=0, allow_inf_nan=False)
    utilities_cost: StrictFloat | None = Field(default=None, ge=0, allow_inf_nan=False)
    other_fixed_cost: StrictFloat | None = Field(default=None, ge=0, allow_inf_nan=False)
    target_daily_orders: StrictInt | None = Field(default=None, ge=0)
    monthly_rent: StrictFloat | None = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator(
        "gross_margin",
        "labor_cost",
        "utilities_cost",
        "other_fixed_cost",
        "monthly_rent",
        mode="before",
    )
    @classmethod
    def require_json_float(cls, value: Any) -> Any:
        if value is not None and (
            type(value) not in (int, float)
            or isinstance(value, bool)
            or not isfinite(value)
        ):
            raise ValueError("finance float fields require finite JSON numbers")
        return value

    @field_validator("target_daily_orders", mode="before")
    @classmethod
    def require_json_int(cls, value: Any) -> Any:
        if value is not None and type(value) is not int:
            raise ValueError("target_daily_orders must be an integer")
        return value


class LocationRequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: StrictInt = Field(gt=0)
    city: str = Field(min_length=1, max_length=80)
    district: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=80)
    target_customer: str = Field(min_length=1, max_length=200)
    planned_average_order_value: StrictFloat = Field(gt=0, allow_inf_nan=False)
    finance_assumptions: FinanceAssumptions | None = None
    coordinate_system: CoordinateSystem = "bd09ll"
    radius_meters: StrictInt = Field(default=1500, ge=300, le=5000)

    @field_validator("project_id", "radius_meters", mode="before")
    @classmethod
    def require_base_int(cls, value: Any) -> Any:
        if type(value) is not int:
            raise ValueError("integer fields must be JSON integers")
        return value

    @field_validator("planned_average_order_value", mode="before")
    @classmethod
    def require_order_value_float(cls, value: Any) -> Any:
        if (
            type(value) not in (int, float)
            or isinstance(value, bool)
            or not isfinite(value)
        ):
            raise ValueError("planned_average_order_value must be a finite float")
        return value


class ManualLocationAnalysisRequest(LocationRequestBase):
    address: str | None = Field(default=None, min_length=1, max_length=500)
    latitude: StrictFloat | None = Field(default=None, ge=-90, le=90)
    longitude: StrictFloat | None = Field(default=None, ge=-180, le=180)

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def require_coordinate_float(cls, value: Any) -> Any:
        if value is not None and (
            type(value) not in (int, float)
            or isinstance(value, bool)
            or not isfinite(value)
        ):
            raise ValueError("coordinates must be finite floats")
        return value

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
    # Shared client form payloads may include an empty address; recommendations
    # still reject any non-null address through this strict None field.
    address: None = None
    candidate_count: StrictInt = Field(default=5, ge=1, le=10)

    @field_validator("candidate_count", mode="before")
    @classmethod
    def require_candidate_int(cls, value: Any) -> Any:
        if type(value) is not int:
            raise ValueError("candidate_count must be an integer")
        return value


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
