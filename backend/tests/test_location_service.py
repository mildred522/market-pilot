from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
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


def test_finance_inputs_change_persisted_finance_metrics_and_feasibility():
    first_session = make_session()
    first = make_service(first_session, Collector(), Snapshots()).analyze_manual(
        project_id=1,
        city="Chengdu",
        category="milk-tea",
        latitude=30.5728,
        longitude=104.0668,
        planned_average_order_value=20,
        finance_assumptions={
            "gross_margin": 0.65,
            "labor_cost": 30000,
            "utilities_cost": 5000,
            "other_fixed_cost": 3000,
            "target_daily_orders": 100,
            "monthly_rent": 20000,
        },
    )
    second_session = make_session()
    second = make_service(second_session, Collector(), Snapshots()).analyze_manual(
        project_id=1,
        city="Chengdu",
        category="milk-tea",
        latitude=30.5728,
        longitude=104.0668,
        planned_average_order_value=40,
        finance_assumptions={
            "gross_margin": 0.65,
            "labor_cost": 30000,
            "utilities_cost": 5000,
            "other_fixed_cost": 3000,
            "target_daily_orders": 100,
            "monthly_rent": 20000,
        },
    )

    assert first.result_json["finance_feasibility"] == "infeasible"
    assert second.result_json["finance_feasibility"] == "feasible"
    assert (
        first.result_json["finance_metrics"]["planned_daily_revenue"]
        < second.result_json["finance_metrics"]["planned_daily_revenue"]
    )


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


class SelectiveScreeningCollector(ScreeningCollector):
    def __init__(self, errors):
        super().__init__()
        self.errors = errors

    def collect(self, *, candidate, radius_meters, queries):
        index = int(candidate.representative.uid.split("-")[-1])
        if index in self.errors:
            self.calls.append(
                {
                    "candidate": candidate,
                    "radius_meters": radius_meters,
                    "queries": queries,
                }
            )
            raise self.errors[index]
        return super().collect(
            candidate=candidate,
            radius_meters=radius_meters,
            queries=queries,
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


def test_recommendations_propagate_requested_radius_to_screening_collection_and_scope():
    session = make_session()
    collector = Collector()
    screening = ScreeningCollector()
    service = make_service(
        session,
        collector,
        Snapshots(),
        screening_collector=screening,
    )
    service._candidate_generator = CandidateSource(3)

    analysis = service.analyze_recommendations(
        project_id=1,
        city="Chengdu",
        region="High-tech Zone",
        category="milk-tea",
        max_candidates=1,
        radius_meters=600,
    )

    assert analysis.input_scope_json["radius_meters"] == 600
    assert all(call["radius_meters"] == 600 for call in screening.calls)
    assert all(call["max_radius_meters"] == 600 for call in collector.calls)
    assert len(analysis.result_json["candidates"]) == 1


def test_recommendations_return_requested_upper_bound_after_ten_deep_analyses():
    session = make_session()
    service = make_service(
        session,
        Collector(),
        Snapshots(),
        screening_collector=ScreeningCollector(),
    )
    service._candidate_generator = CandidateSource(12)

    analysis = service.analyze_recommendations(
        project_id=1,
        city="Chengdu",
        region="High-tech Zone",
        category="milk-tea",
        max_candidates=10,
    )

    assert analysis.result_json["candidate_count"] == 10
    assert len(analysis.result_json["candidates"]) == 10


def test_recommendation_finance_assumptions_affect_each_candidate_result():
    session = make_session()
    service = make_service(
        session,
        Collector(),
        Snapshots(),
        screening_collector=ScreeningCollector(),
    )
    service._candidate_generator = CandidateSource(3)

    analysis = service.analyze_recommendations(
        project_id=1,
        city="Chengdu",
        region="High-tech Zone",
        category="milk-tea",
        max_candidates=3,
        planned_average_order_value=40,
        finance_assumptions={
            "gross_margin": 0.65,
            "labor_cost": 30000,
            "utilities_cost": 5000,
            "other_fixed_cost": 3000,
            "target_daily_orders": 100,
            "monthly_rent": 20000,
        },
    )

    candidates = analysis.result_json["candidates"]
    assert {item["result"]["finance_feasibility"] for item in candidates} == {
        "feasible"
    }
    assert all(
        item["result"]["finance_metrics"]["planned_average_order_value"] == 40
        for item in candidates
    )


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


def test_recommendations_propagate_degraded_child_status_and_warnings():
    session = make_session()
    collector = Collector(
        result=PoiCollectionResult(
            normalized_pois(),
            truncated=True,
            warnings=["child collection incomplete"],
        )
    )
    screening = ScreeningCollector()
    service = make_service(
        session,
        collector,
        Snapshots(),
        screening_collector=screening,
    )
    service._candidate_generator = CandidateSource(3)

    analysis = service.analyze_recommendations(
        project_id=1,
        city="Chengdu",
        region="High-tech Zone",
        category="milk-tea",
        max_candidates=3,
    )

    assert analysis.status == "degraded"
    assert len(analysis.result_json["candidates"]) == 3
    assert "Candidate 00:child collection incomplete" in analysis.warnings_json
    assert all(
        candidate["status"] == "degraded"
        and candidate["warnings"] == ["child collection incomplete"]
        for candidate in analysis.result_json["candidates"]
    )


def test_recommendations_preserve_snapshot_info_without_degrading_parent():
    session = make_session()
    service = make_service(
        session,
        Collector(error=AssertionError("collector must not be called")),
        Snapshots(reusable_snapshot()),
        screening_collector=ScreeningCollector(),
    )
    service._candidate_generator = CandidateSource(3)

    analysis = service.analyze_recommendations(
        project_id=1,
        city="Chengdu",
        region="High-tech Zone",
        category="milk-tea",
        max_candidates=3,
    )

    assert analysis.status == "completed"
    assert all(
        candidate["status"] == "completed"
        for candidate in analysis.result_json["candidates"]
    )
    assert len(analysis.warnings_json) == 3
    assert all("snapshot reuse:id=7" in item for item in analysis.warnings_json)


def test_partial_screening_failure_persists_degraded_successful_candidates():
    session = make_session()
    collector = Collector()
    screening = SelectiveScreeningCollector(
        {
            3: BaiduMapResponseError(
                "quota",
                provider_status=4,
                kind=BaiduMapErrorKind.QUOTA,
                retryable=False,
            )
        }
    )
    service = make_service(
        session,
        collector,
        Snapshots(),
        screening_collector=screening,
    )
    service._candidate_generator = CandidateSource(4)

    analysis = service.analyze_recommendations(
        project_id=1,
        city="Chengdu",
        region="High-tech Zone",
        category="milk-tea",
        max_candidates=3,
    )

    assert analysis.status == "degraded"
    assert analysis.result_json["candidate_count"] == 3
    assert len(collector.calls) == 3
    assert len(screening.calls) == 4
    assert analysis.warnings_json == [
        "candidate_screening:anchor-3:baidu_map:quota:permanent"
    ]
    assert session.get(LocationAnalysis, analysis.id).status == "degraded"


def test_all_retryable_screening_transport_failures_persist_degraded_record():
    session = make_session()
    request = httpx.Request("GET", "https://api.map.baidu.com")
    screening = SelectiveScreeningCollector(
        {
            index: httpx.ConnectError("offline", request=request)
            for index in range(3)
        }
    )
    collector = Collector()
    service = make_service(
        session,
        collector,
        Snapshots(),
        screening_collector=screening,
    )
    service._candidate_generator = CandidateSource(3)

    analysis = service.analyze_recommendations(
        project_id=1,
        city="Chengdu",
        region="High-tech Zone",
        category="milk-tea",
        max_candidates=3,
    )

    assert analysis.status == "degraded"
    assert analysis.result_json["candidate_count"] == 0
    assert collector.calls == []
    assert len(screening.calls) == 3
    assert (
        "candidate_screening:anchor-0:baidu_map:transport:retryable"
        in analysis.warnings_json
    )
    assert session.get(LocationAnalysis, analysis.id) is not None


def test_all_permanent_screening_failures_persist_failed_without_retry():
    session = make_session()
    screening = SelectiveScreeningCollector(
        {
            index: BaiduMapResponseError(
                "permission",
                provider_status=3,
                kind=BaiduMapErrorKind.PERMISSION,
                retryable=False,
            )
            for index in range(3)
        }
    )
    collector = Collector()
    service = make_service(
        session,
        collector,
        Snapshots(),
        screening_collector=screening,
    )
    service._candidate_generator = CandidateSource(3)

    analysis = service.analyze_recommendations(
        project_id=1,
        city="Chengdu",
        region="High-tech Zone",
        category="milk-tea",
        max_candidates=3,
    )

    assert analysis.status == "failed"
    assert analysis.result_json["candidate_count"] == 0
    assert collector.calls == []
    assert len(screening.calls) == 3
    assert analysis.warnings_json[0] == (
        "candidate_screening:anchor-0:baidu_map:permission:permanent"
    )
    assert session.get(LocationAnalysis, analysis.id).status == "failed"


@pytest.mark.parametrize("invalid_count", [True, False, 3.0, -1, 0, 11])
def test_recommendations_reject_requested_counts_outside_three_to_five(
    invalid_count,
):
    session = make_session()
    service = make_service(session, Collector(), Snapshots())
    source = CandidateSource(5)
    service._candidate_generator = source

    with pytest.raises(ValueError, match="between 1 and 10"):
        service.analyze_recommendations(
            project_id=1,
            city="Chengdu",
            region="High-tech Zone",
            category="milk-tea",
            max_candidates=invalid_count,
        )

    assert source.generated_regions == []
    assert session.scalars(select(LocationAnalysis)).all() == []


class FailOnSecondCollection(Collector):
    def collect_competitors(self, **kwargs):
        if len(self.calls) == 1:
            raise RuntimeError("later child failed")
        return super().collect_competitors(**kwargs)


def test_recommendations_roll_back_flushed_children_after_later_child_error():
    session = make_session()
    service = make_service(
        session,
        FailOnSecondCollection(),
        Snapshots(),
        screening_collector=ScreeningCollector(),
    )
    service._candidate_generator = CandidateSource(3)

    with pytest.raises(RuntimeError, match="later child failed"):
        service.analyze_recommendations(
            project_id=1,
            city="Chengdu",
            region="High-tech Zone",
            category="milk-tea",
            max_candidates=3,
        )

    assert session.scalars(select(LocationAnalysis)).all() == []


def test_recommendations_roll_back_children_when_parent_persistence_fails(
    monkeypatch,
):
    session = make_session()
    service = make_service(
        session,
        Collector(),
        Snapshots(),
        screening_collector=ScreeningCollector(),
    )
    service._candidate_generator = CandidateSource(3)
    original_persist = service._persist

    def fail_parent(**kwargs):
        if kwargs["mode"] == "recommendations":
            raise RuntimeError("parent persistence failed")
        return original_persist(**kwargs)

    monkeypatch.setattr(service, "_persist", fail_parent)

    with pytest.raises(RuntimeError, match="parent persistence failed"):
        service.analyze_recommendations(
            project_id=1,
            city="Chengdu",
            region="High-tech Zone",
            category="milk-tea",
            max_candidates=3,
        )

    assert session.scalars(select(LocationAnalysis)).all() == []


def test_recommendations_commit_parent_and_children_once(monkeypatch):
    session = make_session()
    service = make_service(
        session,
        Collector(),
        Snapshots(),
        screening_collector=ScreeningCollector(),
    )
    service._candidate_generator = CandidateSource(3)
    original_commit = session.commit
    commit_calls = 0

    def counting_commit():
        nonlocal commit_calls
        commit_calls += 1
        return original_commit()

    monkeypatch.setattr(session, "commit", counting_commit)

    analysis = service.analyze_recommendations(
        project_id=1,
        city="Chengdu",
        region="High-tech Zone",
        category="milk-tea",
        max_candidates=3,
    )

    assert analysis.id is not None
    assert commit_calls == 1
    assert len(session.scalars(select(LocationAnalysis)).all()) == 4


def test_recommendations_roll_back_on_final_commit_error(monkeypatch):
    session = make_session()
    service = make_service(
        session,
        Collector(),
        Snapshots(),
        screening_collector=ScreeningCollector(),
    )
    service._candidate_generator = CandidateSource(3)
    original_commit = session.commit

    def fail_commit():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="commit failed"):
        service.analyze_recommendations(
            project_id=1,
            city="Chengdu",
            region="High-tech Zone",
            category="milk-tea",
            max_candidates=3,
        )

    monkeypatch.setattr(session, "commit", original_commit)
    assert session.scalars(select(LocationAnalysis)).all() == []
