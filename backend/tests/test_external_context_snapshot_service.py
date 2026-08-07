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


def test_find_latest_stale_returns_latest_expired_exact_signature_only():
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    scope = {
        "keywords": ("milk-tea",),
        "radii": (300, 500, 800, 1500),
        "keyword_classifications": {"milk-tea": "direct_competitor"},
        "scoring_version": "location-v1",
    }
    with make_session() as session:
        project = Project(name="Chengdu milk tea", stage="pre_open")
        session.add(project)
        session.flush()
        service = ExternalContextSnapshotService()
        older = service.save(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=1500,
            queried_at=now - timedelta(days=10),
            context=make_long_lived_context(now - timedelta(days=10)),
            **scope,
        )
        latest = service.save(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=1500,
            queried_at=now - timedelta(days=8),
            context=make_long_lived_context(now - timedelta(days=8)),
            **scope,
        )
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
            **scope,
        )

        found = service.find_latest_stale(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=1500,
            now=now,
            **scope,
        )

        assert older.id != latest.id
        assert found is not None
        assert found.id == latest.id
        assert service.find_latest_stale(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=800,
            now=now,
            **scope,
        ) is None


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
            keyword_classifications={
                "奶茶": "direct_competitor",
                "茶饮": "direct_competitor",
            },
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
            keyword_classifications={
                "奶茶": "direct_competitor",
                "茶饮": "direct_competitor",
            },
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
            keyword_classifications={
                "奶茶": "direct_competitor",
                "茶饮": "direct_competitor",
            },
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
            keyword_classifications={
                keyword: "direct_competitor" for keyword in keywords
            },
            scoring_version=scoring_version,
        )

        assert reused is None


@pytest.mark.parametrize(
    ("parameter", "changed_value"),
    [
        ("page_size", 10),
        ("filter", "industry_type:life"),
        ("scope", 1),
        ("coord_type", 1),
        ("radius_limit", False),
    ],
)
def test_signature_aware_reuse_misses_changed_provider_parameter(
    parameter: str,
    changed_value: object,
):
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    base_scope = {
        "keywords": ("奶茶", "茶饮"),
        "radii": (300, 500, 800, 1500),
        "keyword_classifications": {
            "奶茶": "direct_competitor",
            "茶饮": "direct_competitor",
        },
        "scoring_version": "location-v1",
        "page_size": 20,
        "filter": "industry_type:cater",
        "scope": 2,
        "coord_type": 3,
        "radius_limit": True,
    }
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
            **base_scope,
        )

        changed_scope = {**base_scope, parameter: changed_value}
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
            **changed_scope,
        )

        assert reused is None


@pytest.mark.parametrize(
    ("changed_keyword_classifications", "changed_max_pages"),
    [
        ({"奶茶": "direct_competitor", "茶饮": "substitute"}, 8),
        ({"奶茶": "direct_competitor", "茶饮": "direct_competitor"}, 7),
    ],
)
def test_signature_aware_reuse_misses_changed_collection_scope(
    changed_keyword_classifications: dict[str, str],
    changed_max_pages: int,
):
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    base_scope = {
        "keywords": ("奶茶", "茶饮"),
        "radii": (300, 500, 800, 1500),
        "scoring_version": "location-v1",
        "keyword_classifications": {
            "奶茶": "direct_competitor",
            "茶饮": "direct_competitor",
        },
        "max_pages": 8,
    }
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
            **base_scope,
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
            **{
                **base_scope,
                "keyword_classifications": changed_keyword_classifications,
                "max_pages": changed_max_pages,
            },
        )

        assert reused is None


def test_signature_canonicalizes_decimal_radii_and_strips_scoring_version():
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
            keywords=("奶茶",),
            radii=("300.50",),
            keyword_classifications={"奶茶": "direct_competitor"},
            scoring_version=" location-v1 ",
        )

        assert service.find_reusable(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=1500,
            now=now + timedelta(days=1),
            keywords=("奶茶",),
            radii=(300.5,),
            keyword_classifications={"奶茶": "direct_competitor"},
            scoring_version="location-v1",
        ) is not None
        assert service.find_reusable(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=1500,
            now=now + timedelta(days=1),
            keywords=("奶茶",),
            radii=(300,),
            keyword_classifications={"奶茶": "direct_competitor"},
            scoring_version="location-v1",
        ) is None


def test_signature_aware_scope_requires_complete_keyword_classifications():
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    common = {
        "project_id": 1,
        "provider": "baidu_map",
        "city": "chengdu",
        "category": "milk-tea",
        "latitude": 30.5728,
        "longitude": 104.0668,
        "radius_meters": 1500,
        "queried_at": now,
        "context": make_long_lived_context(now),
        "keywords": ("奶茶", "茶饮"),
        "radii": (300, 500, 800, 1500),
        "scoring_version": "location-v1",
    }
    with make_session() as session:
        project = Project(name="Chengdu milk tea", stage="pre_open")
        session.add(project)
        session.flush()
        common["project_id"] = project.id
        service = ExternalContextSnapshotService()

        with pytest.raises(ValueError, match="keyword_classifications"):
            service.save(session, **common)
        with pytest.raises(ValueError, match="keyword_classifications"):
            service.save(
                session,
                **common,
                keyword_classifications={"奶茶": "direct_competitor"},
            )


def test_effective_max_pages_makes_requested_eight_and_hundred_same_scope():
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    scope = {
        "keywords": ("奶茶",),
        "radii": (300, 500, 800, 1500),
        "keyword_classifications": {"奶茶": "direct_competitor"},
        "scoring_version": "location-v1",
    }
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
            max_pages=100,
            **scope,
        )

        assert service.find_reusable(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=1500,
            now=now + timedelta(days=1),
            max_pages=8,
            **scope,
        ) is not None


@pytest.mark.parametrize(
    ("parameter", "invalid_value"),
    [("max_pages", 0), ("page_size", 0), ("page_size", 21)],
)
def test_snapshot_scope_rejects_invalid_pagination_bounds(
    parameter: str,
    invalid_value: int,
):
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    scope = {
        "keywords": ("奶茶",),
        "radii": (300,),
        "keyword_classifications": {"奶茶": "direct_competitor"},
        "scoring_version": "location-v1",
    }
    with make_session() as session:
        project = Project(name="Chengdu milk tea", stage="pre_open")
        session.add(project)
        session.flush()
        service = ExternalContextSnapshotService()
        with pytest.raises(ValueError, match=parameter):
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
                **scope,
                **{parameter: invalid_value},
            )
        with pytest.raises(ValueError, match=parameter):
            service.find_reusable(
                session,
                project_id=project.id,
                provider="baidu_map",
                city="chengdu",
                category="milk-tea",
                latitude=30.5728,
                longitude=104.0668,
                radius_meters=1500,
                now=now,
                **scope,
                **{parameter: invalid_value},
            )


def test_signature_normalizes_multi_class_keyword_sets_order_insensitively():
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    scope = {
        "keywords": ("奶茶",),
        "radii": (300,),
        "scoring_version": "location-v1",
    }
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
            keyword_classifications={
                "奶茶": ["direct_competitor", "substitute"]
            },
            **scope,
        )

        common = {
            "project_id": project.id,
            "provider": "baidu_map",
            "city": "chengdu",
            "category": "milk-tea",
            "latitude": 30.5728,
            "longitude": 104.0668,
            "radius_meters": 1500,
            "now": now + timedelta(days=1),
            **scope,
        }
        assert service.find_reusable(
            session,
            **common,
            keyword_classifications={
                "奶茶": ["substitute", "direct_competitor"]
            },
        ) is not None
        assert service.find_reusable(
            session,
            **common,
            keyword_classifications={"奶茶": ["direct_competitor"]},
        ) is None


def test_signature_rejects_duplicate_normalized_keyword_classification_keys():
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    with make_session() as session:
        project = Project(name="Chengdu milk tea", stage="pre_open")
        session.add(project)
        session.flush()

        with pytest.raises(ValueError, match="duplicate"):
            ExternalContextSnapshotService().save(
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
                radii=(300,),
                keyword_classifications={
                    "奶茶": ["direct_competitor"],
                    " 奶茶 ": ["substitute"],
                },
                scoring_version="location-v1",
            )


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
            keyword_classifications={"奶茶": "direct_competitor"},
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
            keyword_classifications={"奶茶": "direct_competitor"},
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
            keyword_classifications={"奶茶": "direct_competitor"},
            scoring_version="location-v1",
        ) is None
