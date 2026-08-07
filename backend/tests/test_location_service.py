from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, LocationAnalysis, Project
from app.external_context.baidu_client import (
    BaiduMapErrorKind,
    BaiduMapResponseError,
)
from app.external_context.contracts import EvidenceRecord, ExternalContextData
from app.external_context.reference_repository import ReferenceDatasetRepository
from app.external_context.snapshot_service import ExternalContextSnapshotService
from app.location.collector import PoiCollectionResult
from app.location.candidates import (
    CandidateAnchor,
    LocationCandidate,
    ScreeningMetrics,
)
from app.location.contracts import (
    ConfidenceInputs,
    DimensionScores,
    Evidence,
    FinanceFeasibility,
    NormalizedPoiFeature,
)
from app.location.evidence import EvidenceVerificationError, LocationEvidenceVerifier
from app.location.feature_builder import LocationFeatureBuilder
from app.location.scorer import LocationScorer
from app.location.service import LocationAnalysisService

NOW = datetime(2026, 8, 7, 12, tzinfo=UTC)


def make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    project = Project(name="Location project", stage="pre_open")
    session.add(project)
    session.commit()
    return session


def normalized_pois() -> list[NormalizedPoiFeature]:
    return [
        NormalizedPoiFeature(
            uid="tea-1",
            name="Tea shop",
            distance_meters=250,
            matched_keywords=["milk tea"],
            classifications=["direct_competitor"],
            category="beverage shop",
            average_price=18,
            business_status="open",
            comment_count=20,
        ),
        NormalizedPoiFeature(
            uid="metro-1",
            name="Metro",
            distance_meters=300,
            category="metro station",
            classifications=["transit"],
            business_status="open",
            comment_count=10,
        ),
    ]


class Collector:
    def __init__(self, result=None, error=None):
        self.result = result or PoiCollectionResult(
            normalized_pois(), truncated=False, warnings=[]
        )
        self.error = error
        self.calls = []

    def collect_competitors(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class Snapshots:
    def __init__(self, reusable=None, stale=None):
        self.reusable = reusable
        self.stale = stale
        self.saved = []

    def find_reusable(self, session, **kwargs):
        return self.reusable

    def find_latest_stale(self, session, **kwargs):
        return self.stale

    def save(self, session, **kwargs):
        self.saved.append(kwargs)
        return SimpleNamespace(id=99)


def result_with_evidence(labels: list[str], *, confidence: float = 1):
    scorer = LocationScorer()
    evidence = [
        Evidence(
            source="baidu_map",
            label=label,
            observed_at=NOW,
            expires_at=NOW + timedelta(days=7),
            query_scope={"region": "test"},
            value=1,
        )
        for label in labels
    ]
    return scorer.score(
        DimensionScores(
            competition_balance=70,
            demand_proxies=70,
            transit=70,
            price_fit=70,
            surrounding_synergy=70,
        ),
        ConfidenceInputs(
            pagination=confidence,
            key_fields=confidence,
            keyword_coverage=confidence,
            freshness=confidence,
            status_comment_coverage=confidence,
        ),
        finance_feasibility=FinanceFeasibility.FEASIBLE,
        evidence=evidence,
    )


def test_location_analysis_model_is_create_all_compatible_and_centers_are_nullable():
    session = make_session()
    assert "location_analyses" in inspect(session.bind).get_table_names()
    assert {
        "input_scope",
        "result",
        "evidence",
        "warnings",
    }.issubset(
        {
            column["name"]
            for column in inspect(session.bind).get_columns("location_analyses")
        }
    )
    row = LocationAnalysis(
        mode="recommendations",
        project_id=1,
        input_scope_json={"region": "test"},
        status="completed",
        result_json={"candidates": []},
        evidence_json=[],
        warnings_json=[],
    )
    session.add(row)
    session.commit()

    assert row.id is not None
    assert row.center_latitude is None
    assert row.updated_at is not None


def test_evidence_verifier_rejects_missing_dimension_or_conclusion_evidence():
    verifier = LocationEvidenceVerifier()
    with pytest.raises(EvidenceVerificationError, match="dimension.transit"):
        verifier.verify(
            result_with_evidence(
                [
                    "dimension.competition_balance",
                    "dimension.demand_proxies",
                    "dimension.price_fit",
                    "dimension.surrounding_synergy",
                    "conclusion",
                ]
            )
        )


def test_evidence_verifier_requires_explicit_low_confidence_fallback():
    labels = [
        "dimension.competition_balance",
        "dimension.demand_proxies",
        "dimension.transit",
        "dimension.price_fit",
        "dimension.surrounding_synergy",
        "conclusion",
    ]
    verifier = LocationEvidenceVerifier()

    with pytest.raises(EvidenceVerificationError, match="fallback"):
        verifier.verify(result_with_evidence(labels, confidence=0.5))

    verifier.verify(result_with_evidence([*labels, "fallback"], confidence=0.5))


def make_service(
    session,
    collector,
    snapshots,
    *,
    reference_repository=None,
    screening_collector=None,
):
    return LocationAnalysisService(
        session=session,
        baidu_client=object(),
        poi_collector=collector,
        feature_builder=LocationFeatureBuilder(),
        scorer=LocationScorer(),
        snapshot_service=snapshots,
        evidence_verifier=LocationEvidenceVerifier(),
        reference_repository=reference_repository,
        screening_collector=screening_collector,
        now=lambda: NOW,
    )


def reusable_snapshot():
    return SimpleNamespace(
        id=7,
        metrics_json={
            "pois": [item.model_dump(mode="json") for item in normalized_pois()]
        },
        evidence_json=[
            {
                "source": "baidu_map",
                "label": "normalized POI collection",
                "observed_at": NOW.isoformat(),
                "expires_at": (NOW + timedelta(days=7)).isoformat(),
                "scope": {"radius_meters": 1500},
                "value": {"poi_count": 2},
            }
        ],
        warnings_json=[],
        queried_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )


def test_analyze_manual_persists_normalized_result_evidence_and_snapshot():
    session = make_session()
    collector = Collector()
    snapshots = Snapshots()

    analysis = make_service(session, collector, snapshots).analyze_manual(
        project_id=1,
        city="Chengdu",
        category="milk-tea",
        latitude=30.5728,
        longitude=104.0668,
        finance_feasibility=FinanceFeasibility.FEASIBLE,
    )

    persisted = session.scalar(
        select(LocationAnalysis).where(LocationAnalysis.id == analysis.id)
    )
    assert persisted is not None
    assert persisted.mode == "manual"
    assert persisted.status == "completed"
    assert persisted.center_latitude == 30.5728
    assert persisted.result_json["opportunity_score"] >= 0
    assert len(persisted.evidence_json) >= 6
    assert snapshots.saved[0]["context"].metrics["pois"][0]["uid"] == "tea-1"
    assert "raw_response" not in snapshots.saved[0]["context"].metrics


def test_analyze_manual_reuses_exact_snapshot_without_supplier_call():
    session = make_session()
    collector = Collector(error=AssertionError("collector must not be called"))
    snapshots = Snapshots(reusable_snapshot())

    analysis = make_service(session, collector, snapshots).analyze_manual(
        project_id=1,
        city="Chengdu",
        category="milk-tea",
        latitude=30.5728,
        longitude=104.0668,
    )

    assert collector.calls == []
    assert analysis.status == "completed"
    assert any("snapshot reuse" in warning for warning in analysis.warnings_json)
    assert analysis.result_json["confidence_score"] > 0


def test_analyze_manual_uses_real_stale_snapshot_after_retryable_failure():
    session = make_session()
    snapshots = ExternalContextSnapshotService()
    queried_at = NOW - timedelta(days=8)
    signature = make_service(session, Collector(), snapshots)._scope(
        project_id=1,
        city="chengdu",
        category="milk-tea",
        latitude=30.5728,
        longitude=104.0668,
    )
    signature.pop("now")
    snapshots.save(
        session,
        **signature,
        queried_at=queried_at,
        context=ExternalContextData(
            metrics={
                "pois": [
                    item.model_dump(mode="json") for item in normalized_pois()
                ]
            },
            evidence=[
                EvidenceRecord(
                    source="baidu_map",
                    label="normalized POI collection",
                    observed_at=queried_at,
                    expires_at=queried_at + timedelta(days=30),
                    scope={"radius_meters": 1500},
                    value={"poi_count": 2},
                )
            ],
        ),
    )
    error = BaiduMapResponseError(
        "timeout",
        kind=BaiduMapErrorKind.RETRYABLE,
        retryable=True,
    )

    analysis = make_service(
        session, Collector(error=error), snapshots
    ).analyze_manual(
        project_id=1,
        city="chengdu",
        category="milk-tea",
        latitude=30.5728,
        longitude=104.0668,
    )

    assert analysis.status == "degraded"
    assert analysis.result_json["confidence_score"] < 60
    assert analysis.result_json["conclusion"] == "继续调研"
    assert any("retryable" in warning for warning in analysis.warnings_json)
    assert any("stale snapshot" in warning for warning in analysis.warnings_json)
    assert any(item["label"] == "fallback" for item in analysis.evidence_json)


def test_analyze_manual_uses_reference_baseline_when_retryable_outage_has_no_snapshot():
    session = make_session()
    error = BaiduMapResponseError(
        "timeout",
        kind=BaiduMapErrorKind.RETRYABLE,
        retryable=True,
    )

    analysis = make_service(
        session,
        Collector(error=error),
        Snapshots(),
        reference_repository=ReferenceDatasetRepository(),
    ).analyze_manual(
        project_id=1,
        city="chengdu",
        category="milk-tea",
        latitude=30.5728,
        longitude=104.0668,
    )

    assert analysis.status == "degraded"
    assert analysis.result_json["confidence_score"] < 60
    assert analysis.result_json["conclusion"] == "继续调研"
    assert any("reference fallback" in item for item in analysis.warnings_json)
    fallback = next(
        item for item in analysis.evidence_json if item["label"] == "fallback"
    )
    assert fallback["source"] == "reference_dataset"
    assert fallback["value"]["dataset_ids"] == [
        "category-milk-tea-2025",
        "city-chengdu-2025",
    ]


def test_analyze_manual_persists_classified_permanent_supplier_failure():
    session = make_session()
    error = BaiduMapResponseError(
        "quota exceeded",
        provider_status=4,
        kind=BaiduMapErrorKind.QUOTA,
    )

    analysis = make_service(
        session, Collector(error=error), Snapshots()
    ).analyze_manual(
        project_id=1,
        city="Chengdu",
        category="milk-tea",
        latitude=30.5728,
        longitude=104.0668,
    )

    assert analysis.status == "failed"
    assert analysis.result_json == {}
    assert analysis.evidence_json == []
    assert analysis.warnings_json == ["baidu_map:quota:permanent"]


class CandidateSource:
    def __init__(self, count: int):
        self.candidates = [
            LocationCandidate(
                name=f"Candidate {index:02d}",
                latitude=30 + index / 100,
                longitude=104 + index / 100,
                representative=CandidateAnchor(
                    uid=f"anchor-{index}",
                    name=f"Candidate {index:02d}",
                    latitude=30 + index / 100,
                    longitude=104 + index / 100,
                    anchor_type="shopping_centers",
                    region="High-tech Zone",
                ),
                anchors=(),
            )
            for index in range(count)
        ]
        self.generated_regions = []

    def generate(self, *, region):
        self.generated_regions.append(region)
        return self.candidates

    def screen(self, candidates):
        return list(candidates)


class ScreeningCollector:
    def __init__(self):
        self.calls = []

    def collect(self, *, candidate, radius_meters, queries):
        self.calls.append(
            {
                "candidate": candidate,
                "radius_meters": radius_meters,
                "queries": queries,
            }
        )
        index = int(candidate.representative.uid.split("-")[-1])
        return ScreeningMetrics(
            demand_proxies=index,
            competitors=5,
            transit=index,
        )


def test_recommendations_deep_analyzes_at_most_ten_and_returns_requested_five():
    session = make_session()
    collector = Collector()
    source = CandidateSource(12)
    screening = ScreeningCollector()
    service = make_service(
        session,
        collector,
        Snapshots(),
        screening_collector=screening,
    )
    service._candidate_generator = source

    analysis = service.analyze_recommendations(
        project_id=1,
        city="Chengdu",
        region="High-tech Zone",
        category="milk-tea",
        max_candidates=5,
    )

    assert len(screening.calls) == 12
    assert all(call["radius_meters"] == 1500 for call in screening.calls)
    assert len(collector.calls) == 10
    assert {call["latitude"] for call in collector.calls} == {
        30 + index / 100 for index in range(2, 12)
    }
    assert len(analysis.result_json["candidates"]) == 5
    assert analysis.mode == "recommendations"
    assert analysis.center_latitude is None
    assert source.generated_regions == ["High-tech Zone"]
    assert analysis.result_json["candidates"][0]["transition_input"] == {
        "latitude": 30.02,
        "longitude": 104.02,
        "coordinate_system": "bd09ll",
    }


def test_recommendations_return_actual_insufficient_candidates_without_invention():
    session = make_session()
    collector = Collector()
    screening = ScreeningCollector()
    service = make_service(
        session,
        collector,
        Snapshots(),
        screening_collector=screening,
    )
    service._candidate_generator = CandidateSource(2)

    analysis = service.analyze_recommendations(
        project_id=1,
        city="Chengdu",
        region="High-tech Zone",
        category="milk-tea",
        max_candidates=3,
    )

    assert len(collector.calls) == 2
    assert len(screening.calls) == 2
    assert len(analysis.result_json["candidates"]) == 2
    assert any("insufficient candidates" in item for item in analysis.warnings_json)


@pytest.mark.parametrize("invalid_count", [2, 6])
def test_recommendations_reject_requested_counts_outside_three_to_five(
    invalid_count,
):
    service = make_service(make_session(), Collector(), Snapshots())
    service._candidate_generator = CandidateSource(5)

    with pytest.raises(ValueError, match="between 3 and 5"):
        service.analyze_recommendations(
            project_id=1,
            city="Chengdu",
            region="High-tech Zone",
            category="milk-tea",
            max_candidates=invalid_count,
        )
