import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Project
from app.external_context.analyzer import ExternalContextAnalyzer
from app.external_context.baidu_client import BaiduMapClient
from app.external_context.contracts import BaiduPoi, BaiduPoiSearchResult
from app.external_context.snapshot_service import ExternalContextSnapshotService

FIXTURE = Path(__file__).parent / "fixtures/external/baidu_context_sample.json"


def load_sample_result() -> BaiduPoiSearchResult:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json=payload)
    )
    with httpx.Client(transport=transport) as http_client:
        return BaiduMapClient(
            "test-ak", http_client=http_client
        ).search_nearby(
            query="奶茶",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=800,
        )


def test_analyzer_calculates_deterministic_competition_metrics():
    observed_at = datetime(2026, 7, 24, 10, tzinfo=UTC)

    context = ExternalContextAnalyzer().analyze_competition(
        load_sample_result(),
        observed_at=observed_at,
    )

    assert context.metrics["competitor_count"] == 4
    assert context.metrics["sampled_competitor_count"] == 4
    assert context.metrics["average_competitor_rating"] == 4.3
    assert context.metrics["average_competitor_price"] == 15.0
    assert context.metrics["brand_competitor_ratio"] == 0.75
    assert context.metrics["median_competitor_distance_meters"] == 285.0
    assert context.metrics["competition_pressure_score"] == 38.2
    assert context.evidence[0].source == "baidu_map"
    assert (
        context.evidence[0].expires_at
        - context.evidence[0].observed_at
        == timedelta(days=7)
    )
    assert context.warnings == []


def test_analyzer_warns_about_first_page_sample_and_total_cap():
    observed_at = datetime(2026, 7, 24, 10, tzinfo=UTC)
    search_result = BaiduPoiSearchResult(
        query="奶茶",
        center_latitude=30.5728,
        center_longitude=104.0668,
        radius_meters=800,
        total=150,
        pois=[
            BaiduPoi(
                uid="synthetic-cap-poi",
                name="上限测试茶铺",
                latitude=30.573,
                longitude=104.067,
                distance_meters=100,
            )
        ],
    )

    context = ExternalContextAnalyzer().analyze_competition(
        search_result,
        observed_at=observed_at,
    )

    assert any("第一页" in warning for warning in context.warnings)
    assert any("150" in warning for warning in context.warnings)
    assert any("完整度" in warning for warning in context.warnings)


def test_analyzed_context_persists_without_raw_provider_payload_or_key():
    observed_at = datetime(2026, 7, 24, 10, tzinfo=UTC)
    context = ExternalContextAnalyzer().analyze_competition(
        load_sample_result(),
        observed_at=observed_at,
    )
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        project = Project(name="成都奶茶样本", stage="pre_open")
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
            queried_at=observed_at,
            context=context,
        )

        assert snapshot.metrics_json["competitor_count"] == 4
        assert snapshot.evidence_json[0]["source"] == "baidu_map"
        assert "results" not in snapshot.evidence_json[0]
        assert "ak" not in str(snapshot.evidence_json).lower()
