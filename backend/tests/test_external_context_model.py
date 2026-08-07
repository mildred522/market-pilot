from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, ExternalContextSnapshot, Project
from app.external_context.contracts import EvidenceRecord, ExternalContextData


def test_external_context_snapshot_round_trips_normalized_json():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    observed_at = datetime(2026, 7, 24, 10, tzinfo=UTC)
    context = ExternalContextData(
        metrics={"competitor_count": 18},
        evidence=[
            EvidenceRecord(
                source="baidu_map",
                label="800m milk-tea competitors",
                observed_at=observed_at,
                expires_at=observed_at + timedelta(days=7),
                scope={"radius_meters": 800},
                value=18,
            )
        ],
        warnings=[],
    )

    with Session(engine) as session:
        project = Project(name="Chengdu milk tea", stage="pre_open")
        session.add(project)
        session.flush()
        snapshot = ExternalContextSnapshot(
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=800,
            queried_at=observed_at,
            expires_at=observed_at + timedelta(days=7),
            metrics_json=context.metrics,
            evidence_json=[
                item.model_dump(mode="json") for item in context.evidence
            ],
            warnings_json=context.warnings,
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        assert "external_context_snapshots" in inspect(engine).get_table_names()
        assert snapshot.metrics_json == {"competitor_count": 18}
        assert snapshot.evidence_json[0]["source"] == "baidu_map"
        assert snapshot.warnings_json == []
