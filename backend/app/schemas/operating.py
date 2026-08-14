from math import isfinite
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator

from app.agent_runtime.contracts import AnalysisMode


class UploadResponse(BaseModel):
    file_id: int
    project_id: int
    file_type: str
    filename: str
    columns: list[str]
    required_columns: list[str]
    suggested_mapping: dict[str, str]
    missing_columns: list[str]
    row_count: int


class OperatingFileSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: StrictInt = Field(gt=0)
    mapping: dict[str, str]


class OperatingCostAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monthly_rent: StrictFloat = Field(ge=0)
    monthly_labor: StrictFloat = Field(ge=0)
    monthly_utilities: StrictFloat = Field(ge=0)
    monthly_marketing: StrictFloat = Field(default=0, ge=0)
    other_fixed_costs: StrictFloat = Field(default=0, ge=0)
    cash_balance: StrictFloat = Field(default=0, ge=0)
    delivery_commission_rate: StrictFloat = Field(default=0.2, ge=0, le=1)
    delivery_packaging_per_order: StrictFloat = Field(default=1.5, ge=0)
    target_avg_order_value: StrictFloat | None = Field(default=None, gt=0)
    target_delivery_contribution_margin: StrictFloat | None = Field(
        default=None, ge=0, le=1
    )
    target_monthly_profit: StrictFloat | None = Field(default=None)

    @field_validator("*", mode="before")
    @classmethod
    def require_finite_json_numbers(cls, value: Any) -> Any:
        if value is None:
            return value
        if type(value) not in (int, float) or isinstance(value, bool) or not isfinite(value):
            raise ValueError("cost assumptions require finite JSON numbers")
        return value


class OperatingAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: StrictInt = Field(gt=0)
    question: str = Field(min_length=1, max_length=500)
    analysis_mode: AnalysisMode = "full"
    orders: OperatingFileSelection
    menu_items: OperatingFileSelection
    reviews: OperatingFileSelection
    cost_assumptions: OperatingCostAssumptions


class OperatingAnalyzeSampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int
    question: str
    analysis_mode: AnalysisMode = "full"
