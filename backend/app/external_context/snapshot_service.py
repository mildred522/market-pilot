import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExternalContextSnapshot
from app.external_context.contracts import ExternalContextData


class ExternalContextSnapshotService:
    MAX_AGE = timedelta(days=7)
    SCOPE_METADATA_KEY = "_snapshot_scope"

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
        keywords: Sequence[str] | None = None,
        radii: Sequence[int] | None = None,
        scoring_version: str | None = None,
    ) -> ExternalContextSnapshot:
        if not context.evidence:
            raise ValueError("snapshot requires at least one evidence record")

        query_signature = self._query_signature(
            provider=provider,
            city=city,
            category=category,
            latitude=latitude,
            longitude=longitude,
            radius_meters=radius_meters,
            keywords=keywords,
            radii=radii,
            scoring_version=scoring_version,
        )
        metrics = dict(context.metrics)
        if query_signature is not None:
            metrics[self.SCOPE_METADATA_KEY] = {
                "query_signature": query_signature,
                "scoring_version": scoring_version,
            }

        snapshot = ExternalContextSnapshot(
            project_id=project_id,
            provider=provider,
            city=city,
            category=category,
            latitude=latitude,
            longitude=longitude,
            radius_meters=radius_meters,
            queried_at=queried_at,
            expires_at=min(
                min(item.expires_at for item in context.evidence),
                queried_at + self.MAX_AGE,
            ),
            metrics_json=metrics,
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
        keywords: Sequence[str] | None = None,
        radii: Sequence[int] | None = None,
        scoring_version: str | None = None,
    ) -> ExternalContextSnapshot | None:
        query_signature = self._query_signature(
            provider=provider,
            city=city,
            category=category,
            latitude=latitude,
            longitude=longitude,
            radius_meters=radius_meters,
            keywords=keywords,
            radii=radii,
            scoring_version=scoring_version,
        )
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
        )
        snapshots = session.scalars(statement)
        if query_signature is None:
            return next(iter(snapshots), None)
        for snapshot in snapshots:
            metadata = snapshot.metrics_json.get(self.SCOPE_METADATA_KEY, {})
            if metadata.get("query_signature") == query_signature:
                return snapshot
        return None

    @staticmethod
    def _query_signature(
        *,
        provider: str,
        city: str,
        category: str,
        latitude: float,
        longitude: float,
        radius_meters: int,
        keywords: Sequence[str] | None,
        radii: Sequence[int] | None,
        scoring_version: str | None,
    ) -> str | None:
        values = (keywords, radii, scoring_version)
        if all(value is None for value in values):
            return None
        if any(value is None for value in values):
            raise ValueError(
                "keywords, radii, and scoring_version must be provided together"
            )
        normalized_keywords = sorted(
            {keyword.strip() for keyword in keywords or () if keyword.strip()}
        )
        normalized_radii = sorted({int(radius) for radius in radii or ()})
        if (
            not normalized_keywords
            or not normalized_radii
            or not scoring_version.strip()
        ):
            raise ValueError("signature-aware query scope cannot be empty")
        scope = {
            "provider": provider,
            "city": city,
            "category": category,
            "latitude": latitude,
            "longitude": longitude,
            "radius_meters": radius_meters,
            "keywords": normalized_keywords,
            "radii": normalized_radii,
            "scoring_version": scoring_version,
        }
        canonical = json.dumps(
            scope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
