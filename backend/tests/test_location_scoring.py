from datetime import UTC, datetime, timedelta

import pytest

from app.location.contracts import (
    ConfidenceInputs,
    DimensionScores,
    Evidence,
    FinanceFeasibility,
    NormalizedPoiFeature,
    OpportunityWeights,
)
from app.location.feature_builder import LocationFeatureBuilder
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
