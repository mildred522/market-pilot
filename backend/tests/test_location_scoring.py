from datetime import UTC, datetime, timedelta
from math import inf, nan

import pytest
from pydantic import ValidationError

from app.location.contracts import (
    ConfidenceComponent,
    ConfidenceInputs,
    DimensionScores,
    Evidence,
    FinanceFeasibility,
    NormalizedPoiFeature,
    OpportunityWeights,
    PriceMetrics,
    PoiClassification,
    RingMetrics,
)
from app.location.feature_builder import LocationFeatureBuilder
from app.location.evidence import LocationEvidenceBuilder
from app.location.scorer import LocationScorer


def poi(
    uid: str,
    name: str,
    distance: int | None,
    *,
    keywords: list[str] | None = None,
    category: str | None = None,
    price: float | None = None,
) -> NormalizedPoiFeature:
    return NormalizedPoiFeature(
        uid=uid,
        name=name,
        distance_meters=distance,
        matched_keywords=keywords or [],
        category=category,
        average_price=price,
    )


def dimensions(value: float) -> DimensionScores:
    return DimensionScores(
        competition_balance=value,
        demand_proxies=value,
        transit=value,
        price_fit=value,
        surrounding_synergy=value,
    )


def full_confidence() -> ConfidenceInputs:
    return ConfidenceInputs(
        pagination=1,
        key_fields=1,
        keyword_coverage=1,
        freshness=1,
        status_comment_coverage=1,
    )


def test_feature_builder_deduplicates_and_builds_cumulative_ring_counts():
    features = LocationFeatureBuilder().build(
        [
            poi("tea-1", "甲茶铺", 250, keywords=["奶茶"], price=12),
            poi("tea-1", "甲茶铺", 260, keywords=["果茶"]),
            poi("tea-2", "乙饮品", 450, category="茶饮店", price=18),
            poi("coffee-1", "咖啡店", 700, keywords=["咖啡"], price=30),
            poi("bus-1", "公交站", 200, category="公交车站"),
            poi("metro-1", "地铁站", 400, category="地铁站"),
            poi("mall-1", "购物中心", 750, category="购物中心"),
            poi("office-1", "写字楼", 1200, category="写字楼"),
        ]
    )

    assert len(features.pois) == 7
    assert features.rings[300].direct_competitors == 1
    assert features.rings[500].direct_competitors == 2
    assert features.rings[800].substitutes == 1
    assert features.rings[1500].substitutes == 1
    assert features.rings[300].transit == 1
    assert features.rings[500].transit == 2
    assert features.rings[800].amenities == 1
    assert features.rings[800].demand_proxies == 1
    assert features.rings[1500].demand_proxies == 2


def test_feature_builder_calculates_price_distribution_and_preserves_missing_values():
    features = LocationFeatureBuilder().build(
        [
            poi("tea-1", "甲茶铺", 250, keywords=["奶茶"], price=12),
            poi("tea-2", "乙茶铺", 450, keywords=["茶饮"], price=18),
            poi("coffee-1", "咖啡店", 700, keywords=["咖啡"], price=30),
            poi("office-1", "写字楼", None, category="写字楼"),
        ]
    )

    assert features.price.sample_count == 3
    assert features.price.coverage == 1
    assert features.price.median == 18
    assert features.price.first_quartile == 15
    assert features.price.third_quartile == 24
    assert features.price.minimum == 12
    assert features.price.maximum == 30
    office = next(item for item in features.pois if item.uid == "office-1")
    assert office.distance_meters is None
    assert office.average_price is None
    assert office.business_status is None


def test_feature_builder_unions_explicit_classifications_when_deduplicating():
    features = LocationFeatureBuilder().build(
        [
            NormalizedPoiFeature(
                uid="shared-poi",
                name="共享点位",
                classifications=[PoiClassification.AMENITY],
            ),
            NormalizedPoiFeature(
                uid="shared-poi",
                name="共享点位",
                classifications=[PoiClassification.TRANSIT],
            ),
        ]
    )

    merged = features.pois[0]
    assert set(merged.classifications) == {
        PoiClassification.AMENITY,
        PoiClassification.TRANSIT,
    }


def test_feature_builder_includes_exact_ring_boundary_and_ignores_missing_distance():
    features = LocationFeatureBuilder().build(
        [
            poi("boundary", "边界竞品", 300, keywords=["奶茶"]),
            poi("outside", "圈外竞品", 301, keywords=["奶茶"]),
            poi("unknown", "距离未知", None, keywords=["奶茶"]),
        ]
    )

    assert features.rings[300].direct_competitors == 1
    assert features.rings[500].direct_competitors == 2
    assert features.rings[1500].direct_competitors == 2


def test_feature_builder_empty_input_preserves_missing_metrics():
    features = LocationFeatureBuilder().build([])

    assert features.pois == []
    assert features.price.eligible_count == 0
    assert features.price.sample_count == 0
    assert features.price.coverage == 0
    assert features.price.median is None
    assert all(ring.direct_competitors == 0 for ring in features.rings.values())


@pytest.mark.parametrize(
    ("requested_radius", "expected_demand"),
    [(300, 15), (499, 15), (500, 30), (799, 30), (800, 45)],
)
def test_dimensions_use_largest_observed_ring_within_requested_radius(
    requested_radius, expected_demand
):
    features = LocationFeatureBuilder().build(
        [
            poi("demand-300", "office", 250, category="写字楼"),
            poi("demand-500", "residence", 450, category="住宅"),
            poi("demand-800", "school", 750, category="学校"),
        ]
    )
    dimensions, _, _ = LocationEvidenceBuilder().build(
        features=features,
        city="Chengdu",
        category="milk-tea",
        latitude=30.5,
        longitude=104.0,
        observed_at=datetime(2026, 8, 7, tzinfo=UTC),
        expires_at=datetime(2026, 8, 14, tzinfo=UTC),
        complete=True,
        radius_meters=requested_radius,
    )
    assert dimensions.demand_proxies == expected_demand


@pytest.mark.parametrize(
    "field_name",
    [
        "distance_meters",
    ],
)
def test_normalized_poi_numeric_fields_reject_negative_values(field_name: str):
    with pytest.raises(ValidationError):
        NormalizedPoiFeature(uid="invalid", name="invalid", **{field_name: -1})


@pytest.mark.parametrize("value", [-1, nan, inf, -inf])
def test_normalized_poi_average_price_rejects_negative_and_non_finite_values(
    value: float,
):
    with pytest.raises(ValidationError):
        NormalizedPoiFeature(uid="invalid", name="invalid", average_price=value)


def test_normalized_poi_comment_count_rejects_negative_values():
    with pytest.raises(ValidationError):
        NormalizedPoiFeature(uid="invalid", name="invalid", comment_count=-1)


@pytest.mark.parametrize(
    "field_name",
    [
        "radius_meters",
        "direct_competitors",
        "substitutes",
        "demand_proxies",
        "transit",
        "amenities",
    ],
)
def test_ring_metrics_numeric_fields_reject_negative_values(field_name: str):
    with pytest.raises(ValidationError):
        values = {"radius_meters": 1, field_name: -1}
        RingMetrics(**values)


@pytest.mark.parametrize("field_name", ["weight", "weighted_score"])
def test_confidence_component_scores_reject_negative_values(field_name: str):
    with pytest.raises(ValidationError):
        values = {"raw_coverage": 0, "weight": 1, "weighted_score": 0}
        values[field_name] = -1
        ConfidenceComponent(**values)


@pytest.mark.parametrize("field_name", ["eligible_count", "sample_count"])
def test_price_metric_counts_reject_negative_values(field_name: str):
    with pytest.raises(ValidationError):
        values = {field_name: -1}
        PriceMetrics(**values)


@pytest.mark.parametrize(
    "field_name",
    ["median", "first_quartile", "third_quartile", "minimum", "maximum"],
)
@pytest.mark.parametrize("value", [-1, nan, inf, -inf])
def test_price_metric_values_reject_negative_and_non_finite_values(
    field_name: str,
    value: float,
):
    with pytest.raises(ValidationError):
        values = {field_name: value}
        PriceMetrics(**values)


def test_price_metrics_reject_sample_count_above_eligible_count():
    with pytest.raises(ValidationError, match="sample_count"):
        PriceMetrics(eligible_count=1, sample_count=2, coverage=1)


@pytest.mark.parametrize(
    ("eligible_count", "sample_count", "coverage"),
    [(2, 1, 0.4), (0, 0, 0.1)],
)
def test_price_metrics_reject_inconsistent_coverage(
    eligible_count: int,
    sample_count: int,
    coverage: float,
):
    with pytest.raises(ValidationError, match="coverage"):
        PriceMetrics(
            eligible_count=eligible_count,
            sample_count=sample_count,
            coverage=coverage,
        )


def test_price_metrics_require_all_distribution_fields_together():
    with pytest.raises(ValidationError, match="distribution"):
        PriceMetrics(median=15)


def test_price_metrics_reject_distribution_without_samples():
    with pytest.raises(ValidationError, match="sample_count"):
        PriceMetrics(
            minimum=10,
            first_quartile=12,
            median=15,
            third_quartile=18,
            maximum=20,
        )


def test_price_metrics_reject_unordered_distribution():
    with pytest.raises(ValidationError, match="ordered"):
        PriceMetrics(
            eligible_count=1,
            sample_count=1,
            coverage=1,
            minimum=10,
            first_quartile=15,
            median=12,
            third_quartile=18,
            maximum=20,
        )


def test_price_metrics_accept_valid_empty_and_nonempty_models():
    empty = PriceMetrics()
    populated = PriceMetrics(
        eligible_count=3,
        sample_count=2,
        coverage=0.6667,
        minimum=10,
        first_quartile=12,
        median=15,
        third_quartile=18,
        maximum=20,
    )

    assert empty.coverage == 0
    assert populated.sample_count == 2
    assert populated.median == 15


def test_confidence_below_60_forces_further_research_and_returns_raw_coverage():
    result = LocationScorer().score(
        dimensions(90),
        ConfidenceInputs(
            pagination=0.5,
            key_fields=0.5,
            keyword_coverage=0.5,
            freshness=0.5,
            status_comment_coverage=0.5,
        ),
        finance_feasibility=FinanceFeasibility.FEASIBLE,
    )

    assert result.opportunity_score == 90
    assert result.confidence_score == 50
    assert result.confidence.pagination.raw_coverage == 0.5
    assert result.confidence.pagination.weight == 30
    assert result.conclusion == "继续调研"


@pytest.mark.parametrize(
    ("dimension_value", "expected_score"),
    [(0, 0), (49, 49), (50, 50), (69, 69), (70, 70), (100, 100)],
)
def test_opportunity_score_preserves_boundaries(
    dimension_value: float,
    expected_score: float,
):
    result = LocationScorer().score(
        dimensions(dimension_value),
        full_confidence(),
        finance_feasibility=FinanceFeasibility.FEASIBLE,
    )

    assert result.opportunity_score == expected_score
    assert result.dimension_scores.competition_weighted == pytest.approx(
        dimension_value * 0.25
    )
    assert result.dimension_scores.demand_weighted == pytest.approx(
        dimension_value * 0.25
    )


def test_opportunity_weights_are_configurable():
    scorer = LocationScorer(
        OpportunityWeights(
            competition_balance=100,
            demand_proxies=0,
            transit=0,
            price_fit=0,
            surrounding_synergy=0,
        )
    )
    result = scorer.score(
        DimensionScores(
            competition_balance=80,
            demand_proxies=0,
            transit=0,
            price_fit=0,
            surrounding_synergy=0,
        ),
        full_confidence(),
        finance_feasibility=FinanceFeasibility.FEASIBLE,
    )

    assert result.opportunity_score == 80


@pytest.mark.parametrize(
    ("score", "finance", "expected"),
    [
        (70, FinanceFeasibility.FEASIBLE, "建议开"),
        (69, FinanceFeasibility.FEASIBLE, "调整后再开"),
        (85, FinanceFeasibility.ADJUSTABLE, "调整后再开"),
        (49, FinanceFeasibility.FEASIBLE, "不建议开"),
        (85, FinanceFeasibility.INFEASIBLE, "不建议开"),
        (85, FinanceFeasibility.MISSING, "继续调研"),
    ],
)
def test_conclusion_rules_cover_all_labels(
    score: float,
    finance: FinanceFeasibility,
    expected: str,
):
    result = LocationScorer().score(
        dimensions(score),
        full_confidence(),
        finance_feasibility=finance,
    )

    assert result.finance_feasibility == finance
    assert result.conclusion == expected


def test_analysis_result_keeps_evidence_and_scores_explicit():
    observed_at = datetime(2026, 8, 7, 10, tzinfo=UTC)
    evidence = Evidence(
        source="baidu_map",
        label="800m direct competitors",
        observed_at=observed_at,
        expires_at=observed_at + timedelta(days=7),
        query_scope={"radius_meters": 800},
        value=8,
    )

    result = LocationScorer().score(
        dimensions(70),
        full_confidence(),
        finance_feasibility=FinanceFeasibility.FEASIBLE,
        evidence=[evidence],
    )

    assert result.evidence == [evidence]
    assert result.opportunity_score == 70
    assert result.confidence_score == 100
    assert result.finance_feasibility == FinanceFeasibility.FEASIBLE
    assert result.conclusion == "建议开"
