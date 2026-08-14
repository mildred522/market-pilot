import pytest

from app.agent_runtime.contracts import CapabilityIntent
from app.location.service import LocationAnalysisService


@pytest.mark.parametrize(
    ("intent", "has_address", "has_coordinates", "expected"),
    [
        (CapabilityIntent.ANALYZE_LOCATION, True, False, "manual"),
        (CapabilityIntent.ANALYZE_LOCATION, False, True, "manual"),
        (CapabilityIntent.RECOMMEND_LOCATIONS, False, False, "recommendations"),
    ],
)
def test_location_capability_selects_only_a_validated_domain_mode(
    intent, has_address, has_coordinates, expected
):
    assert (
        LocationAnalysisService.select_capability_mode(
            intent=intent,
            has_address=has_address,
            has_coordinates=has_coordinates,
        )
        == expected
    )


def test_manual_location_intent_requires_one_specific_location_source():
    with pytest.raises(ValueError, match="specific address or coordinates"):
        LocationAnalysisService.select_capability_mode(
            intent=CapabilityIntent.ANALYZE_LOCATION,
            has_address=False,
            has_coordinates=False,
        )


def test_recommendation_intent_rejects_a_specific_location():
    with pytest.raises(ValueError, match="does not accept"):
        LocationAnalysisService.select_capability_mode(
            intent=CapabilityIntent.RECOMMEND_LOCATIONS,
            has_address=True,
            has_coordinates=False,
        )


def test_location_capability_rejects_non_location_intents():
    with pytest.raises(ValueError, match="location intent"):
        LocationAnalysisService.select_capability_mode(
            intent=CapabilityIntent.ASSESS_FEASIBILITY,
            has_address=False,
            has_coordinates=False,
        )
