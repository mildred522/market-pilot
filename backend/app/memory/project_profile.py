from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project, ProjectProfile, utc_now


class ProjectProfileService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def upsert_confirmed(
        self,
        *,
        project: Project,
        city: str | None = None,
        category: str | None = None,
        merchant_targets: dict[str, Any] | None = None,
        cost_assumptions: dict[str, Any] | None = None,
        preferences: dict[str, Any] | None = None,
        source: str,
    ) -> ProjectProfile:
        profile = self._db.scalar(
            select(ProjectProfile).where(ProjectProfile.project_id == project.id)
        )
        if profile is None:
            profile = ProjectProfile(
                project_id=project.id,
                store_identity=project.name,
                current_stage=project.stage,
                city=city,
                category=category,
                merchant_targets_json=merchant_targets or {},
                cost_assumptions_json=cost_assumptions or {},
                preferences_json=preferences or {},
                sources_json={},
            )
            self._db.add(profile)
        else:
            profile.store_identity = project.name
            profile.current_stage = project.stage
            if city is not None:
                profile.city = city
            if category is not None:
                profile.category = category
            if merchant_targets is not None:
                profile.merchant_targets_json = {
                    **profile.merchant_targets_json,
                    **merchant_targets,
                }
            if cost_assumptions is not None:
                profile.cost_assumptions_json = {
                    **profile.cost_assumptions_json,
                    **cost_assumptions,
                }
            if preferences is not None:
                profile.preferences_json = {
                    **profile.preferences_json,
                    **preferences,
                }
        sources = dict(profile.sources_json or {})
        for field, value in (
            ("city", city),
            ("category", category),
            ("merchant_targets", merchant_targets),
            ("cost_assumptions", cost_assumptions),
            ("preferences", preferences),
        ):
            if value is not None:
                sources[field] = source
        profile.sources_json = sources
        profile.observed_at = utc_now()
        self._db.flush()
        return profile

    def enrich_metrics(
        self, project_id: int, metrics: dict[str, Any]
    ) -> dict[str, Any]:
        profile = self._db.scalar(
            select(ProjectProfile).where(ProjectProfile.project_id == project_id)
        )
        if profile is None:
            return dict(metrics)
        report_targets = metrics.get("_targets")
        targets = {
            **profile.merchant_targets_json,
            **(report_targets if isinstance(report_targets, dict) else {}),
        }
        return {
            **metrics,
            "_targets": targets,
            "_project_profile": {
                "store_identity": profile.store_identity,
                "current_stage": profile.current_stage,
                "city": profile.city,
                "category": profile.category,
                "preferences": profile.preferences_json,
                "sources": profile.sources_json,
            },
        }
