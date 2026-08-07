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
