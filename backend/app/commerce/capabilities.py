from __future__ import annotations

from collections.abc import Collection

from app.commerce.contracts import (
    CapabilityAvailability,
    CommerceCapability,
)


CAPABILITY_REQUIREMENTS: dict[CommerceCapability, frozenset[CommerceCapability]] = {
    CommerceCapability.CATALOG: frozenset({CommerceCapability.CATALOG}),
    CommerceCapability.SALES: frozenset(
        {CommerceCapability.CATALOG, CommerceCapability.SALES}
    ),
    CommerceCapability.REVIEWS: frozenset({CommerceCapability.REVIEWS}),
    CommerceCapability.COSTS: frozenset({CommerceCapability.COSTS}),
    CommerceCapability.INVENTORY: frozenset({CommerceCapability.INVENTORY}),
    CommerceCapability.RETURNS: frozenset({CommerceCapability.RETURNS}),
    CommerceCapability.TRAFFIC: frozenset({CommerceCapability.TRAFFIC}),
    CommerceCapability.CAMPAIGNS: frozenset({CommerceCapability.CAMPAIGNS}),
}


def check_capability(
    capability: CommerceCapability,
    available: Collection[CommerceCapability],
) -> CapabilityAvailability:
    available_set = set(available)
    requirements = CAPABILITY_REQUIREMENTS[capability]
    missing = tuple(sorted(requirements - available_set, key=lambda item: item.value))
    if not missing:
        return CapabilityAvailability(capability=capability, status="supported")
    if available_set.intersection(requirements):
        return CapabilityAvailability(
            capability=capability,
            status="partial",
            missing=missing,
            reason="some required commerce capabilities are unavailable",
        )
    return CapabilityAvailability(
        capability=capability,
        status="unsupported",
        missing=missing,
        reason="required commerce capabilities are unavailable",
    )
