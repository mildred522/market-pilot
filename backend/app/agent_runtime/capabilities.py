from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field

from app.agent_runtime.contracts import CapabilityName


class CapabilityDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: CapabilityName
    project_stage: str
    required_inputs: tuple[str, ...] = Field(min_length=1)
    uses_external_data: bool
    output_contract: str
    limitations: tuple[str, ...] = Field(min_length=1)
    forbidden_controls: tuple[str, ...] = ()
    domain_service: str


_CAPABILITIES = {
    CapabilityName.PRE_OPEN_FEASIBILITY: CapabilityDefinition(
        name=CapabilityName.PRE_OPEN_FEASIBILITY,
        project_stage="pre_open",
        required_inputs=(
            "project_id",
            "category",
            "city",
            "location_type",
            "area_sqm",
            "seats",
            "monthly_rent",
            "total_investment",
            "own_capital",
            "debt_amount",
            "expected_daily_orders",
            "expected_avg_order_value",
            "expected_gross_margin",
            "is_franchise",
            "franchise_fee",
            "competitor_count",
            "storefront_visibility",
        ),
        uses_external_data=False,
        output_contract="PreOpenAnalyzeResponse",
        limitations=(
            "User forecasts are assumptions rather than observed performance.",
            "The assessment is a decision aid, not a guarantee of store success.",
        ),
        domain_service="app.pre_open.service.PreOpenAssessmentService",
    ),
    CapabilityName.LOCATION_ANALYSIS: CapabilityDefinition(
        name=CapabilityName.LOCATION_ANALYSIS,
        project_stage="pre_open",
        required_inputs=(
            "project_id",
            "city",
            "district",
            "category",
            "target_customer",
            "planned_average_order_value",
            "intent",
            "address_or_coordinates_for_manual_analysis",
        ),
        uses_external_data=True,
        output_contract="LocationAnalysisResponse",
        limitations=(
            "Map POI coverage does not represent observed pedestrian traffic.",
            "Location scores are planning signals, not success probabilities.",
        ),
        forbidden_controls=(
            "keywords",
            "pagination",
            "raw_provider_parameters",
            "scoring_weights",
            "transaction_boundaries",
            "snapshot_reuse",
        ),
        domain_service="app.location.service.LocationAnalysisService",
    ),
    CapabilityName.OPERATING_DIAGNOSIS: CapabilityDefinition(
        name=CapabilityName.OPERATING_DIAGNOSIS,
        project_stage="operating",
        required_inputs=(
            "project_id",
            "question",
            "orders",
            "menu_items",
            "reviews",
            "cost_assumptions",
        ),
        uses_external_data=False,
        output_contract="OperatingAnalysisReport",
        limitations=(
            "Findings are limited to uploaded data and declared assumptions.",
            "The Agent cannot infer unrecorded offline transactions.",
        ),
        domain_service="app.services.agent_service.AgentService",
    ),
}

CAPABILITY_REGISTRY = MappingProxyType(_CAPABILITIES)
