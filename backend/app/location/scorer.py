from app.location.contracts import (
    ConfidenceBreakdown,
    ConfidenceComponent,
    ConfidenceInputs,
    Conclusion,
    DimensionScoreBreakdown,
    DimensionScores,
    Evidence,
    FinanceFeasibility,
    LocationAnalysisResult,
    OpportunityWeights,
)

CONFIDENCE_WEIGHTS = {
    "pagination": 30,
    "key_fields": 25,
    "keyword_coverage": 20,
    "freshness": 15,
    "status_comment_coverage": 10,
}


class LocationScorer:
    def __init__(
        self,
        opportunity_weights: OpportunityWeights | None = None,
    ) -> None:
        self.opportunity_weights = (
            opportunity_weights
            if opportunity_weights is not None
            else OpportunityWeights()
        )

    def score(
        self,
        dimensions: DimensionScores,
        confidence_inputs: ConfidenceInputs,
        *,
        finance_feasibility: FinanceFeasibility,
        evidence: list[Evidence] | None = None,
    ) -> LocationAnalysisResult:
        dimension_breakdown = self._dimension_breakdown(dimensions)
        opportunity_score = round(
            dimension_breakdown.competition_weighted
            + dimension_breakdown.demand_weighted
            + dimension_breakdown.transit_weighted
            + dimension_breakdown.price_weighted
            + dimension_breakdown.synergy_weighted,
            2,
        )
        confidence = self._confidence_breakdown(confidence_inputs)
        confidence_score = round(
            sum(
                component.weighted_score
                for component in (
                    confidence.pagination,
                    confidence.key_fields,
                    confidence.keyword_coverage,
                    confidence.freshness,
                    confidence.status_comment_coverage,
                )
            ),
            2,
        )
        conclusion = self._conclusion(
            opportunity_score,
            confidence_score,
            finance_feasibility,
        )
        return LocationAnalysisResult(
            opportunity_score=opportunity_score,
            confidence_score=confidence_score,
            finance_feasibility=finance_feasibility,
            conclusion=conclusion,
            dimension_scores=dimension_breakdown,
            confidence=confidence,
            evidence=evidence or [],
        )

    def _dimension_breakdown(
        self,
        dimensions: DimensionScores,
    ) -> DimensionScoreBreakdown:
        weights = self.opportunity_weights
        return DimensionScoreBreakdown(
            **dimensions.model_dump(),
            competition_weighted=_weighted(
                dimensions.competition_balance,
                weights.competition_balance,
            ),
            demand_weighted=_weighted(
                dimensions.demand_proxies,
                weights.demand_proxies,
            ),
            transit_weighted=_weighted(dimensions.transit, weights.transit),
            price_weighted=_weighted(dimensions.price_fit, weights.price_fit),
            synergy_weighted=_weighted(
                dimensions.surrounding_synergy,
                weights.surrounding_synergy,
            ),
        )

    @staticmethod
    def _confidence_breakdown(
        inputs: ConfidenceInputs,
    ) -> ConfidenceBreakdown:
        return ConfidenceBreakdown(
            **{
                name: ConfidenceComponent(
                    raw_coverage=getattr(inputs, name),
                    weight=weight,
                    weighted_score=round(
                        getattr(inputs, name) * weight,
                        2,
                    ),
                )
                for name, weight in CONFIDENCE_WEIGHTS.items()
            }
        )

    @staticmethod
    def _conclusion(
        opportunity_score: float,
        confidence_score: float,
        finance_feasibility: FinanceFeasibility,
    ) -> Conclusion:
        if (
            confidence_score < 60
            or finance_feasibility == FinanceFeasibility.MISSING
        ):
            return "继续调研"
        if (
            opportunity_score < 50
            or finance_feasibility == FinanceFeasibility.INFEASIBLE
        ):
            return "不建议开"
        if (
            opportunity_score >= 70
            and finance_feasibility == FinanceFeasibility.FEASIBLE
        ):
            return "建议开"
        return "调整后再开"


def _weighted(score: float, weight: int) -> float:
    return round(score * weight / 100, 2)
