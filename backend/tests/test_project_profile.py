from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, Project
from app.memory.project_profile import ProjectProfileService


def test_profile_persists_only_explicit_confirmed_operating_facts():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="确认信息面馆", stage="operating")
        db.add(project)
        db.flush()

        profile = ProjectProfileService(db).upsert_confirmed(
            project=project,
            city=None,
            category=None,
            merchant_targets={"metrics.revenue.avg_order_value": 45.0},
            cost_assumptions={"monthly_rent": 18000.0},
            preferences={"report_detail": "concise"},
            source="user_input",
        )

        assert profile.store_identity == "确认信息面馆"
        assert profile.current_stage == "operating"
        assert profile.city is None
        assert profile.category is None
        assert profile.merchant_targets_json == {
            "metrics.revenue.avg_order_value": 45.0
        }
        assert profile.cost_assumptions_json == {"monthly_rent": 18000.0}
        assert profile.sources_json["cost_assumptions"] == "user_input"


def test_profile_update_does_not_erase_omitted_confirmed_facts():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="稳定信息店", stage="pre_open")
        db.add(project)
        db.flush()
        service = ProjectProfileService(db)
        service.upsert_confirmed(
            project=project,
            city="成都",
            category="奶茶",
            source="user_input",
        )

        profile = service.upsert_confirmed(
            project=project,
            merchant_targets={"metrics.revenue.avg_order_value": 28.0},
            source="user_input",
        )

        assert profile.city == "成都"
        assert profile.category == "奶茶"


def test_profile_enriches_report_targets_without_overwriting_report_values():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="目标复用店", stage="operating")
        db.add(project)
        db.flush()
        service = ProjectProfileService(db)
        service.upsert_confirmed(
            project=project,
            merchant_targets={
                "metrics.revenue.avg_order_value": 45.0,
                "metrics.survival.projected_monthly_profit": 10000.0,
            },
            source="user_input",
        )

        enriched = service.enrich_metrics(
            project.id,
            {
                "_targets": {"metrics.revenue.avg_order_value": 50.0},
                "revenue": {"avg_order_value": 42.0},
            },
        )

        assert enriched["_targets"] == {
            "metrics.revenue.avg_order_value": 50.0,
            "metrics.survival.projected_monthly_profit": 10000.0,
        }
