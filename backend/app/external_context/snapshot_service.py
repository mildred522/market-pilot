from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExternalContextSnapshot
from app.external_context.contracts import ExternalContextData


class ExternalContextSnapshotService:
    def save(
        self,
        session: Session,
        *,
        project_id: int,
        provider: str,
        city: str,
        category: str,
        latitude: float,
        longitude: float,
        radius_meters: int,
        queried_at: datetime,
        context: ExternalContextData,
    ) -> ExternalContextSnapshot:
        if not context.evidence:
            raise ValueError("snapshot requires at least one evidence record")

        snapshot = ExternalContextSnapshot(
            project_id=project_id,
            provider=provider,
            city=city,
            category=category,
            latitude=latitude,
            longitude=longitude,
            radius_meters=radius_meters,
            queried_at=queried_at,
            expires_at=min(item.expires_at for item in context.evidence),
            metrics_json=context.metrics,
            evidence_json=[
                item.model_dump(mode="json") for item in context.evidence
            ],
            warnings_json=context.warnings,
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)
        return snapshot

    def find_reusable(
        self,
        session: Session,
        *,
        project_id: int,
        provider: str,
        city: str,
        category: str,
        latitude: float,
        longitude: float,
        radius_meters: int,
        now: datetime,
    ) -> ExternalContextSnapshot | None:
        statement = (
            select(ExternalContextSnapshot)
            .where(
                ExternalContextSnapshot.project_id == project_id,
                ExternalContextSnapshot.provider == provider,
                ExternalContextSnapshot.city == city,
                ExternalContextSnapshot.category == category,
                ExternalContextSnapshot.latitude == latitude,
                ExternalContextSnapshot.longitude == longitude,
                ExternalContextSnapshot.radius_meters == radius_meters,
                ExternalContextSnapshot.expires_at > now,
            )
            .order_by(ExternalContextSnapshot.queried_at.desc())
            .limit(1)
        )
        return session.scalar(statement)
