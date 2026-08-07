from collections.abc import Sequence
from datetime import datetime
from math import isclose, isfinite
from typing import Any

from app.location.contracts import (
    ConfidenceInputs,
    DimensionScores,
    Evidence,
    LocationAnalysisResult,
    LocationFeatures,
)
from app.location.feature_builder import RING_RADII

CONFIDENCE_FIELDS = (
    "pagination",
    "key_fields",
    "keyword_coverage",
    "freshness",
    "status_comment_coverage",
)


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
        fallback: bool = False,
        radius_meters: int = max(RING_RADII),
    ) -> tuple[DimensionScores, ConfidenceInputs, list[Evidence]]:
        dimensions = self._dimensions(features, radius_meters=radius_meters)
        observed_radii = [radius for radius in RING_RADII if radius <= radius_meters]
        unobserved_radii = [radius for radius in RING_RADII if radius > radius_meters]
        scope = {
            "city": city,
            "category": category,
            "center": {"latitude": latitude, "longitude": longitude},
            "radius_meters": radius_meters,
            "radii_meters": observed_radii,
            "unobserved_rings_meters": unobserved_radii,
        }
        confidence = self._confidence(
            features, complete, fallback, radius_meters=radius_meters
        )
        metrics: dict[str, Any] = {
            "competition_balance": {
                "score": dimensions.competition_balance,
                "rings": {
                    str(radius): item.model_dump(mode="json")
                    for radius, item in features.rings.items()
                    if radius <= radius_meters
                },
                "unobserved_rings_meters": unobserved_radii,
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
        evidence.extend(
            Evidence(
                source="baidu_map",
                label=f"confidence.{name}",
                observed_at=observed_at,
                expires_at=expires_at,
                query_scope=scope,
                value=getattr(confidence, name),
            )
            for name in CONFIDENCE_FIELDS
        )
        return dimensions, confidence, evidence

    @staticmethod
    def _dimensions(
        features: LocationFeatures, *, radius_meters: int
    ) -> DimensionScores:
        observed_radii = [
            radius
            for radius in features.rings
            if radius <= radius_meters
        ]
        if not observed_radii:
            raise ValueError("requested radius has no observed scoring ring")
        ring = features.rings[max(observed_radii)]
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
        features: LocationFeatures,
        complete: bool,
        fallback: bool,
        *,
        radius_meters: int,
    ) -> ConfidenceInputs:
        pois = features.pois
        count = len(pois)
        coverage = min(1, radius_meters / max(RING_RADII))
        if not count:
            return ConfidenceInputs(
                pagination=(1 if complete else 0) * coverage,
                key_fields=0,
                keyword_coverage=coverage,
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
            pagination=(0 if fallback else (1 if complete else 0.5)) * coverage,
            key_fields=key_fields,
            keyword_coverage=(0.5 if fallback else 1) * coverage,
            freshness=0 if fallback else 1,
            status_comment_coverage=status_comments,
        )


class LocationEvidenceVerifier:
    ALLOWED_SOURCES = frozenset({"baidu_map", "reference_dataset"})
    OPPORTUNITY_LABELS = (
        "dimension.competition_balance",
        "dimension.demand_proxies",
        "dimension.transit",
        "dimension.price_fit",
        "dimension.surrounding_synergy",
    )
    CONFIDENCE_LABELS = tuple(
        f"confidence.{field_name}" for field_name in CONFIDENCE_FIELDS
    )
    REQUIRED_LABELS = (*OPPORTUNITY_LABELS, *CONFIDENCE_LABELS, "conclusion")

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
            if item.source not in self.ALLOWED_SOURCES:
                raise EvidenceVerificationError(
                    f"evidence {item.label!r} has an unsupported source"
                )
            self._verify_scope(item.label, item.query_scope)
            self._verify_metric_values(item.label, item.value)
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

        evidence_by_label = {item.label: item for item in result.evidence}
        for label in self.OPPORTUNITY_LABELS:
            metric = self._metric_value(label, evidence_by_label[label].value)
            field_name = label.removeprefix("dimension.")
            expected = getattr(result.dimension_scores, field_name)
            if not isclose(metric, expected, rel_tol=0, abs_tol=1e-6):
                raise EvidenceVerificationError(
                    f"evidence {label!r} does not match the scored dimension"
                )
        for label in self.CONFIDENCE_LABELS:
            metric = self._metric_value(label, evidence_by_label[label].value)
            field_name = label.removeprefix("confidence.")
            expected = getattr(result.confidence, field_name).raw_coverage
            if not isclose(metric, expected, rel_tol=0, abs_tol=1e-6):
                raise EvidenceVerificationError(
                    f"evidence {label!r} does not match the confidence breakdown"
                )
        if evidence_by_label["conclusion"].value != result.conclusion:
            raise EvidenceVerificationError(
                "conclusion evidence does not match the persisted conclusion"
            )

    @staticmethod
    def _verify_scope(label: str, scope: dict[str, Any]) -> None:
        center = scope.get("center")
        radius = scope.get("radius_meters")
        if not isinstance(center, dict):
            raise EvidenceVerificationError(
                f"evidence {label!r} requires a center scope"
            )
        latitude = center.get("latitude")
        longitude = center.get("longitude")
        if (
            isinstance(latitude, bool)
            or not isinstance(latitude, (int, float))
            or not isfinite(latitude)
            or not -90 <= latitude <= 90
            or isinstance(longitude, bool)
            or not isinstance(longitude, (int, float))
            or not isfinite(longitude)
            or not -180 <= longitude <= 180
        ):
            raise EvidenceVerificationError(
                f"evidence {label!r} has an invalid center scope"
            )
        if (
            isinstance(radius, bool)
            or not isinstance(radius, int)
            or not 300 <= radius <= 5000
        ):
            raise EvidenceVerificationError(
                f"evidence {label!r} has an invalid radius scope"
            )

    @classmethod
    def _verify_metric_values(cls, label: str, value: Any) -> None:
        if isinstance(value, bool):
            raise EvidenceVerificationError(
                f"evidence {label!r} contains an invalid metric value"
            )
        if isinstance(value, (int, float)) and not isfinite(value):
            raise EvidenceVerificationError(
                f"evidence {label!r} contains a non-finite metric value"
            )
        if isinstance(value, dict):
            for nested in value.values():
                cls._verify_metric_values(label, nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                cls._verify_metric_values(label, nested)

    @staticmethod
    def _metric_value(label: str, value: Any) -> float:
        metric = value.get("score") if isinstance(value, dict) else value
        if (
            isinstance(metric, bool)
            or not isinstance(metric, (int, float))
            or not isfinite(metric)
        ):
            raise EvidenceVerificationError(
                f"evidence {label!r} requires a finite numeric score"
            )
        return float(metric)
