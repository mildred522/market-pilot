from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.location.contracts import (
    ConfidenceInputs,
    DimensionScores,
    Evidence,
    LocationAnalysisResult,
    LocationFeatures,
)
from app.location.feature_builder import RING_RADII


class EvidenceVerificationError(ValueError):
    pass


class LocationEvidenceBuilder:
    def build(
        self,
        *,
        features: LocationFeatures,
        city: str,
        category: str,
        latitude: float,
        longitude: float,
        observed_at: datetime,
        expires_at: datetime,
        complete: bool,
    ) -> tuple[DimensionScores, ConfidenceInputs, list[Evidence]]:
        dimensions = self._dimensions(features)
        scope = {
            "city": city,
            "category": category,
            "center": {"latitude": latitude, "longitude": longitude},
            "radii_meters": list(RING_RADII),
        }
        metrics: dict[str, Any] = {
            "competition_balance": {
                "score": dimensions.competition_balance,
                "rings": {
                    str(radius): item.model_dump(mode="json")
                    for radius, item in features.rings.items()
                },
            },
            "demand_proxies": dimensions.demand_proxies,
            "transit": dimensions.transit,
            "price_fit": {
                "score": dimensions.price_fit,
                "price": features.price.model_dump(mode="json"),
            },
            "surrounding_synergy": dimensions.surrounding_synergy,
        }
        evidence = [
            Evidence(
                source="baidu_map",
                label=f"dimension.{name}",
                observed_at=observed_at,
                expires_at=expires_at,
                query_scope=scope,
                value=value,
            )
            for name, value in metrics.items()
        ]
        return dimensions, self._confidence(features, complete), evidence

    @staticmethod
    def _dimensions(features: LocationFeatures) -> DimensionScores:
        ring = features.rings[800]
        competitors = ring.direct_competitors + ring.substitutes
        return DimensionScores(
            competition_balance=max(0, 100 - abs(competitors - 5) * 12),
            demand_proxies=min(100, ring.demand_proxies * 15),
            transit=min(100, ring.transit * 25),
            price_fit=50 if features.price.sample_count else 0,
            surrounding_synergy=min(100, ring.amenities * 15),
        )

    @staticmethod
    def _confidence(
        features: LocationFeatures, complete: bool
    ) -> ConfidenceInputs:
        pois = features.pois
        count = len(pois)
        if not count:
            return ConfidenceInputs(
                pagination=1 if complete else 0,
                key_fields=0,
                keyword_coverage=0,
                freshness=1,
                status_comment_coverage=0,
            )
        key_fields = sum(
            poi.distance_meters is not None and poi.category is not None
            for poi in pois
        ) / count
        status_comments = sum(
            (poi.business_status is not None) + (poi.comment_count is not None)
            for poi in pois
        ) / (count * 2)
        return ConfidenceInputs(
            pagination=1 if complete else 0.5,
            key_fields=key_fields,
            keyword_coverage=1,
            freshness=1,
            status_comment_coverage=status_comments,
        )


class LocationEvidenceVerifier:
    REQUIRED_LABELS = (
        "dimension.competition_balance",
        "dimension.demand_proxies",
        "dimension.transit",
        "dimension.price_fit",
        "dimension.surrounding_synergy",
        "conclusion",
    )

    def verify(
        self,
        result: LocationAnalysisResult,
        *,
        warnings: Sequence[str] = (),
    ) -> None:
        labels = {item.label for item in result.evidence}
        missing = [label for label in self.REQUIRED_LABELS if label not in labels]
        if missing:
            raise EvidenceVerificationError(
                f"missing required evidence: {', '.join(missing)}"
            )
        for item in result.evidence:
            if not item.source or not item.query_scope:
                raise EvidenceVerificationError(
                    f"evidence {item.label!r} requires source and query scope"
                )
            if item.expires_at <= item.observed_at:
                raise EvidenceVerificationError(
                    f"evidence {item.label!r} must expire after observation"
                )
        fallback_is_explicit = "fallback" in labels or any(
            "fallback" in warning.lower() or "low confidence" in warning.lower()
            for warning in warnings
        )
        if result.confidence_score < 60 and not fallback_is_explicit:
            raise EvidenceVerificationError(
                "low confidence result requires explicit fallback evidence or warning"
            )
