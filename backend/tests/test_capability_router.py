import pytest

from app.agent_runtime.capabilities import CAPABILITY_REGISTRY
from app.agent_runtime.contracts import CapabilityIntent, CapabilityName
from app.agent_runtime.request_router import CapabilityRoutingError, route_capability


def test_registry_declares_all_bounded_business_capabilities():
    assert set(CAPABILITY_REGISTRY) == {
        CapabilityName.PRE_OPEN_FEASIBILITY,
        CapabilityName.LOCATION_ANALYSIS,
        CapabilityName.OPERATING_DIAGNOSIS,
    }

    location = CAPABILITY_REGISTRY[CapabilityName.LOCATION_ANALYSIS]
    assert location.uses_external_data is True
    assert location.domain_service == "app.location.service.LocationAnalysisService"
    assert "raw_provider_parameters" in location.forbidden_controls
    assert location.output_contract == "LocationAnalysisResponse"


@pytest.mark.parametrize(
    ("intent", "stage", "expected"),
    [
        (
            CapabilityIntent.ASSESS_FEASIBILITY,
            "pre_open",
            CapabilityName.PRE_OPEN_FEASIBILITY,
        ),
        (
            CapabilityIntent.ANALYZE_LOCATION,
            "pre_open",
            CapabilityName.LOCATION_ANALYSIS,
        ),
        (
            CapabilityIntent.RECOMMEND_LOCATIONS,
            "pre_open",
            CapabilityName.LOCATION_ANALYSIS,
        ),
        (
            CapabilityIntent.DIAGNOSE_OPERATIONS,
            "operating",
            CapabilityName.OPERATING_DIAGNOSIS,
        ),
    ],
)
def test_router_uses_validated_intent_and_project_stage(intent, stage, expected):
    decision = route_capability(intent=intent, project_stage=stage)

    assert decision.capability == expected
    assert decision.intent == intent


def test_router_rejects_capability_that_is_invalid_for_project_stage():
    with pytest.raises(CapabilityRoutingError, match="not available"):
        route_capability(
            intent=CapabilityIntent.DIAGNOSE_OPERATIONS,
            project_stage="pre_open",
        )
