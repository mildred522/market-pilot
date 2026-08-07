from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Project
from app.external_context.contracts import EvidenceRecord, ExternalContextData
from app.external_context.snapshot_service import ExternalContextSnapshotService


def make_context(now: datetime) -> ExternalContextData:
    return ExternalContextData(
        metrics={"competitor_count": 18},
        evidence=[
            EvidenceRecord(
                source="baidu_map",
                label="competitors",
                observed_at=now,
                expires_at=now + timedelta(days=7),
                scope={"radius_meters": 800},
                value=18,
            ),
            EvidenceRecord(
                source="baidu_weather",
                label="weather",
                observed_at=now,
                expires_at=now + timedelta(hours=1),
                scope={"city": "chengdu"},
                value="rain",
            ),
        ],
    )


def make_long_lived_context(now: datetime) -> ExternalContextData:
    return ExternalContextData(
        metrics={"competitor_count": 18},
        evidence=[
            EvidenceRecord(
                source="baidu_map",
                label="competitors",
                observed_at=now,
                expires_at=now + timedelta(days=30),
                scope={"radius_meters": 800},
                value=18,
            )
        ],
    )


def make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def test_save_uses_earliest_evidence_expiry():
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    with make_session() as session:
        project = Project(name="Chengdu milk tea", stage="pre_open")
        session.add(project)
        session.flush()
        snapshot = ExternalContextSnapshotService().save(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=800,
            queried_at=now,
            context=make_context(now),
        )

        assert snapshot.expires_at.replace(tzinfo=UTC) == now + timedelta(hours=1)


def test_find_reusable_returns_fresh_exact_match_only():
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    with make_session() as session:
        project = Project(name="Chengdu milk tea", stage="pre_open")
        session.add(project)
        session.flush()
        service = ExternalContextSnapshotService()
        service.save(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=800,
            queried_at=now,
            context=make_context(now),
        )

        assert (
            service.find_reusable(
                session,
                project_id=project.id,
                provider="baidu_map",
                city="chengdu",
                category="milk-tea",
                latitude=30.5728,
                longitude=104.0668,
                radius_meters=800,
                now=now + timedelta(minutes=30),
            )
            is not None
        )
        assert (
            service.find_reusable(
                session,
                project_id=project.id,
                provider="baidu_map",
                city="chengdu",
                category="milk-tea",
                latitude=30.5728,
                longitude=104.0668,
                radius_meters=800,
                now=now + timedelta(hours=2),
            )
            is None
        )
        assert (
            service.find_reusable(
                session,
                project_id=project.id,
                provider="baidu_map",
                city="chengdu",
                category="milk-tea",
                latitude=30.5728,
                longitude=104.0668,
                radius_meters=1000,
                now=now + timedelta(minutes=30),
            )
            is None
        )


def test_save_rejects_context_without_evidence():
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    with make_session() as session:
        project = Project(name="Chengdu milk tea", stage="pre_open")
        session.add(project)
        session.flush()

        with pytest.raises(
            ValueError, match="snapshot requires at least one evidence record"
        ):
            ExternalContextSnapshotService().save(
                session,
                project_id=project.id,
                provider="reference",
                city="chengdu",
                category="milk-tea",
                latitude=30.5728,
                longitude=104.0668,
                radius_meters=800,
                queried_at=now,
                context=ExternalContextData(),
            )


def test_signature_aware_reuse_matches_canonical_keyword_and_radius_scope():
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    with make_session() as session:
        project = Project(name="Chengdu milk tea", stage="pre_open")
        session.add(project)
        session.flush()
        service = ExternalContextSnapshotService()
        saved = service.save(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=1500,
            queried_at=now,
            context=make_long_lived_context(now),
            keywords=("茶饮", "奶茶", "奶茶"),
            radii=(1500, 300, 800, 500),
            scoring_version="location-v1",
        )

        reused = service.find_reusable(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=1500,
            now=now + timedelta(days=1),
            keywords=("奶茶", "茶饮"),
            radii=(300, 500, 800, 1500),
            scoring_version="location-v1",
        )

        assert reused is not None
        assert reused.id == saved.id
        assert saved.metrics_json["_snapshot_scope"]["scoring_version"] == (
            "location-v1"
        )


@pytest.mark.parametrize(
    ("keywords", "radii", "scoring_version"),
    [
        (("奶茶", "咖啡"), (300, 500, 800, 1500), "location-v1"),
        (("奶茶", "茶饮"), (300, 500, 800), "location-v1"),
        (("奶茶", "茶饮"), (300, 500, 800, 1500), "location-v2"),
    ],
)
def test_signature_aware_reuse_misses_changed_scope(
    keywords: tuple[str, ...],
    radii: tuple[int, ...],
    scoring_version: str,
):
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    with make_session() as session:
        project = Project(name="Chengdu milk tea", stage="pre_open")
        session.add(project)
        session.flush()
        service = ExternalContextSnapshotService()
        service.save(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=1500,
            queried_at=now,
            context=make_long_lived_context(now),
            keywords=("奶茶", "茶饮"),
            radii=(300, 500, 800, 1500),
            scoring_version="location-v1",
        )

        reused = service.find_reusable(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=1500,
            now=now + timedelta(days=1),
            keywords=keywords,
            radii=radii,
            scoring_version=scoring_version,
        )

        assert reused is None


def test_save_clamps_expiry_to_seven_days_and_lookup_honors_expiry():
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    with make_session() as session:
        project = Project(name="Chengdu milk tea", stage="pre_open")
        session.add(project)
        session.flush()
        service = ExternalContextSnapshotService()
        snapshot = service.save(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=1500,
            queried_at=now,
            context=make_long_lived_context(now),
            keywords=("奶茶",),
            radii=(300, 500, 800, 1500),
            scoring_version="location-v1",
        )

        assert snapshot.expires_at.replace(tzinfo=UTC) == now + timedelta(days=7)
        assert service.find_reusable(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=1500,
            now=now + timedelta(days=7),
            keywords=("奶茶",),
            radii=(300, 500, 800, 1500),
            scoring_version="location-v1",
        ) is None


def test_legacy_snapshot_is_reusable_only_by_legacy_lookup():
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    with make_session() as session:
        project = Project(name="Chengdu milk tea", stage="pre_open")
        session.add(project)
        session.flush()
        service = ExternalContextSnapshotService()
        service.save(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=800,
            queried_at=now,
            context=make_context(now),
        )

        common = {
            "project_id": project.id,
            "provider": "baidu_map",
            "city": "chengdu",
            "category": "milk-tea",
            "latitude": 30.5728,
            "longitude": 104.0668,
            "radius_meters": 800,
            "now": now + timedelta(minutes=30),
        }
        assert service.find_reusable(session, **common) is not None
        assert service.find_reusable(
            session,
            **common,
            keywords=("奶茶",),
            radii=(300, 500, 800, 1500),
            scoring_version="location-v1",
        ) is None
