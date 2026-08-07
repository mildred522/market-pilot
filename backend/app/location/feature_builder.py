from collections.abc import Iterable

from app.location.contracts import (
    LocationFeatures,
    NormalizedPoiFeature,
    PoiClassification,
    PriceMetrics,
    RingMetrics,
)

RING_RADII = (300, 500, 800, 1500)

DIRECT_KEYWORDS = {"奶茶", "茶饮", "现制饮品", "果茶", "饮品店"}
SUBSTITUTE_KEYWORDS = {"咖啡", "甜品"}
DIRECT_CATEGORIES = ("奶茶", "茶饮", "饮品店", "现制饮品", "果茶")
SUBSTITUTE_CATEGORIES = ("咖啡", "甜品")
DEMAND_CATEGORIES = (
    "写字楼",
    "产业园",
    "办公",
    "住宅",
    "社区",
    "学校",
    "大学",
    "学院",
    "购物中心",
    "商场",
    "医院",
    "景区",
)
TRANSIT_CATEGORIES = ("地铁", "公交", "停车场", "交通枢纽")
AMENITY_CATEGORIES = (
    "购物中心",
    "商场",
    "医院",
    "景区",
    "便利店",
    "餐饮",
    "公共设施",
)


class LocationFeatureBuilder:
    def build(
        self,
        pois: Iterable[NormalizedPoiFeature],
    ) -> LocationFeatures:
        normalized = [
            self._classify(poi)
            for poi in self._deduplicate(pois).values()
        ]
        rings = {
            radius: self._ring_metrics(normalized, radius)
            for radius in RING_RADII
        }
        return LocationFeatures(
            pois=normalized,
            rings=rings,
            price=self._price_metrics(normalized),
        )

    @staticmethod
    def _deduplicate(
        pois: Iterable[NormalizedPoiFeature],
    ) -> dict[str, NormalizedPoiFeature]:
        unique: dict[str, NormalizedPoiFeature] = {}
        for poi in pois:
            current = unique.get(poi.uid)
            if current is None:
                unique[poi.uid] = poi.model_copy(deep=True)
                continue
            distances = [
                value
                for value in (current.distance_meters, poi.distance_meters)
                if value is not None
            ]
            unique[poi.uid] = current.model_copy(
                update={
                    "distance_meters": min(distances) if distances else None,
                    "matched_keywords": sorted(
                        set(current.matched_keywords + poi.matched_keywords)
                    ),
                    "category": current.category or poi.category,
                    "average_price": (
                        current.average_price
                        if current.average_price is not None
                        else poi.average_price
                    ),
                    "business_status": (
                        current.business_status or poi.business_status
                    ),
                    "comment_count": (
                        current.comment_count
                        if current.comment_count is not None
                        else poi.comment_count
                    ),
                }
            )
        return unique

    @staticmethod
    def _classify(poi: NormalizedPoiFeature) -> NormalizedPoiFeature:
        keywords = set(poi.matched_keywords)
        category = poi.category or ""
        classifications = set(poi.classifications)
        if keywords & DIRECT_KEYWORDS or _contains(category, DIRECT_CATEGORIES):
            classifications.add(PoiClassification.DIRECT_COMPETITOR)
        if keywords & SUBSTITUTE_KEYWORDS or _contains(
            category, SUBSTITUTE_CATEGORIES
        ):
            classifications.add(PoiClassification.SUBSTITUTE)
        if _contains(category, DEMAND_CATEGORIES):
            classifications.add(PoiClassification.DEMAND_PROXY)
        if _contains(category, TRANSIT_CATEGORIES):
            classifications.add(PoiClassification.TRANSIT)
        if _contains(category, AMENITY_CATEGORIES):
            classifications.add(PoiClassification.AMENITY)
        return poi.model_copy(
            update={"classifications": sorted(classifications, key=str)}
        )

    @staticmethod
    def _ring_metrics(
        pois: list[NormalizedPoiFeature],
        radius: int,
    ) -> RingMetrics:
        included = [
            poi
            for poi in pois
            if poi.distance_meters is not None
            and poi.distance_meters <= radius
        ]
        return RingMetrics(
            radius_meters=radius,
            direct_competitors=_count(
                included, PoiClassification.DIRECT_COMPETITOR
            ),
            substitutes=_count(included, PoiClassification.SUBSTITUTE),
            demand_proxies=_count(included, PoiClassification.DEMAND_PROXY),
            transit=_count(included, PoiClassification.TRANSIT),
            amenities=_count(included, PoiClassification.AMENITY),
        )

    @staticmethod
    def _price_metrics(pois: list[NormalizedPoiFeature]) -> PriceMetrics:
        competitor_types = {
            PoiClassification.DIRECT_COMPETITOR,
            PoiClassification.SUBSTITUTE,
        }
        eligible = [
            poi
            for poi in pois
            if competitor_types.intersection(poi.classifications)
        ]
        prices = sorted(
            float(poi.average_price)
            for poi in eligible
            if poi.average_price is not None
        )
        coverage = len(prices) / len(eligible) if eligible else 0
        if not prices:
            return PriceMetrics(eligible_count=len(eligible), coverage=coverage)
        return PriceMetrics(
            eligible_count=len(eligible),
            sample_count=len(prices),
            coverage=round(coverage, 4),
            median=_percentile(prices, 0.5),
            first_quartile=_percentile(prices, 0.25),
            third_quartile=_percentile(prices, 0.75),
            minimum=prices[0],
            maximum=prices[-1],
        )


def _contains(value: str, candidates: tuple[str, ...]) -> bool:
    return any(candidate in value for candidate in candidates)


def _count(
    pois: list[NormalizedPoiFeature],
    classification: PoiClassification,
) -> int:
    return sum(classification in poi.classifications for poi in pois)


def _percentile(values: list[float], fraction: float) -> float:
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    interpolated = values[lower] + (values[upper] - values[lower]) * (
        position - lower
    )
    return round(interpolated, 2)
