from pydantic import BaseModel, ConfigDict, Field


class PreOpenAssessmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monthly_rent: float = Field(ge=0)
    total_investment: float = Field(ge=0)
    own_capital: float = Field(ge=0)
    debt_amount: float = Field(ge=0)
    expected_daily_orders: int = Field(ge=0)
    expected_avg_order_value: float = Field(ge=0)
    expected_gross_margin: float = Field(ge=0, le=1)
    is_franchise: bool
    franchise_fee: float = Field(ge=0)
    competitor_count: int = Field(ge=0)


class PreOpenMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    estimated_daily_revenue: float
    estimated_daily_gross_profit: float
    daily_rent: float


class PreOpenAssessmentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str
    metrics: PreOpenMetrics
    evidence: tuple[str, ...]
    risks: tuple[str, ...]
    actions: tuple[str, ...]
    limitations: tuple[str, ...]
