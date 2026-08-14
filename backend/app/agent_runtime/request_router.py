from app.agent_runtime.capabilities import CAPABILITY_REGISTRY
from app.agent_runtime.contracts import (
    CapabilityIntent,
    CapabilityName,
    CapabilityRoutingDecision,
)


class CapabilityRoutingError(ValueError):
    pass


_INTENT_CAPABILITIES = {
    CapabilityIntent.ASSESS_FEASIBILITY: CapabilityName.PRE_OPEN_FEASIBILITY,
    CapabilityIntent.ANALYZE_LOCATION: CapabilityName.LOCATION_ANALYSIS,
    CapabilityIntent.RECOMMEND_LOCATIONS: CapabilityName.LOCATION_ANALYSIS,
    CapabilityIntent.DIAGNOSE_OPERATIONS: CapabilityName.OPERATING_DIAGNOSIS,
}


def capability_for_intent(intent: CapabilityIntent) -> CapabilityName:
    return _INTENT_CAPABILITIES[intent]


def route_capability(
    *, intent: CapabilityIntent, project_stage: str
) -> CapabilityRoutingDecision:
    capability = capability_for_intent(intent)
    definition = CAPABILITY_REGISTRY[capability]
    if definition.project_stage != project_stage:
        raise CapabilityRoutingError(
            f"{capability.value} is not available for {project_stage} projects"
        )
    return CapabilityRoutingDecision(
        capability=capability,
        intent=intent,
        project_stage=project_stage,
    )
