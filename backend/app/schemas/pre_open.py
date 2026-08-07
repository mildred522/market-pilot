from pydantic import BaseModel, Field


class PreOpenAnalyzeRequest(BaseModel):
    project_id: int
    category: str
    city: str
    location_type: str
    area_sqm: float = Field(gt=0)
    seats: int = Field(ge=0)
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
    storefront_visibility: str


class PreOpenAnalyzeResponse(BaseModel):
    analysis_id: int
    project_id: int
    stage: str
    summary: str
    metrics: dict[str, float]
    risks: list[str]
    actions: list[str]
