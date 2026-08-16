from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, ExternalContextSnapshot, Project
from app.external_context.followup_provider import PersistedFollowupEvidenceProvider


NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)


def test_provider_loads_sourced_city_and_category_reference_facts():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="外部证据店", stage="operating")
        db.add(project)
        db.flush()
        provider = PersistedFollowupEvidenceProvider(
            db,
            project_id=project.id,
            now=lambda: NOW,
        )

        result = provider.retrieve(
            "external_industry_context",
            {"city": "chengdu", "category": "milk-tea"},
        )

    assert result.status == "completed"
    refs = {fact.canonical_ref for fact in result.facts}
    assert (
        "external.reference.city-chengdu-2025.metrics.food_service_revenue_growth"
        in refs
    )
    category_fact = next(
        fact
        for fact in result.facts
        if fact.canonical_ref.endswith("taste_preference_share")
    )
    assert category_fact.value == 63.0
    assert category_fact.provenance["sources"][0]["url"].startswith("https://")


def test_provider_reads_latest_persisted_competitor_snapshot():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="竞品证据店", stage="operating")
        db.add(project)
        db.flush()
        db.add_all(
            [
                _snapshot(project.id, 3, NOW - timedelta(days=2)),
                _snapshot(project.id, 8, NOW - timedelta(hours=2)),
            ]
        )
        db.flush()
        provider = PersistedFollowupEvidenceProvider(
            db,
            project_id=project.id,
            now=lambda: NOW,
        )

        assert "location_competitors" in provider.available_capabilities({})
        result = provider.retrieve("location_competitors", {})

    assert result.status == "completed"
    competitor_fact = next(
        fact for fact in result.facts if fact.canonical_ref.endswith("competitor_count")
    )
    assert competitor_fact.value == 8
    assert competitor_fact.provenance["radius_meters"] == 1500


def _snapshot(
    project_id: int, competitor_count: int, observed_at: datetime
) -> ExternalContextSnapshot:
    return ExternalContextSnapshot(
        project_id=project_id,
        provider="baidu_map",
        city="chengdu",
        category="milk-tea",
        latitude=30.5728,
        longitude=104.0668,
        radius_meters=1500,
        queried_at=observed_at,
        expires_at=observed_at + timedelta(days=7),
        metrics_json={"competitor_count": competitor_count},
        evidence_json=[],
        warnings_json=["地图 POI 不代表实际客流"],
    )
