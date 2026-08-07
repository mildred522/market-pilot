import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExternalContextSnapshot
from app.external_context.contracts import ExternalContextData


class ExternalContextSnapshotService:
    MAX_AGE = timedelta(days=7)
    MAX_PAGES = 8
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
        keyword_classifications: Mapping[str, object] | None = None,
        scoring_version: str | None = None,
        max_pages: int = 8,
        page_size: int = 20,
        filter: str = "industry_type:cater",
        scope: int = 2,
        coord_type: int = 3,
        radius_limit: bool = True,
        commit: bool = True,
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
            keyword_classifications=keyword_classifications,
            scoring_version=scoring_version,
            max_pages=max_pages,
            page_size=page_size,
            filter=filter,
            scope=scope,
            coord_type=coord_type,
            radius_limit=radius_limit,
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
        if commit:
            session.commit()
            session.refresh(snapshot)
        else:
            session.flush()
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
        keyword_classifications: Mapping[str, object] | None = None,
        scoring_version: str | None = None,
        max_pages: int = 8,
        page_size: int = 20,
        filter: str = "industry_type:cater",
        scope: int = 2,
        coord_type: int = 3,
        radius_limit: bool = True,
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
            keyword_classifications=keyword_classifications,
            scoring_version=scoring_version,
            max_pages=max_pages,
            page_size=page_size,
            filter=filter,
            scope=scope,
            coord_type=coord_type,
            radius_limit=radius_limit,
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

    def find_latest_stale(
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
        keyword_classifications: Mapping[str, object] | None = None,
        scoring_version: str | None = None,
        max_pages: int = 8,
        page_size: int = 20,
        filter: str = "industry_type:cater",
        scope: int = 2,
        coord_type: int = 3,
        radius_limit: bool = True,
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
            keyword_classifications=keyword_classifications,
            scoring_version=scoring_version,
            max_pages=max_pages,
            page_size=page_size,
            filter=filter,
            scope=scope,
            coord_type=coord_type,
            radius_limit=radius_limit,
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
                ExternalContextSnapshot.expires_at <= now,
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
        keyword_classifications: Mapping[str, object] | None,
        scoring_version: str | None,
        max_pages: int,
        page_size: int,
        filter: str,
        scope: int,
        coord_type: int,
        radius_limit: bool,
    ) -> str | None:
        if (
            isinstance(max_pages, bool)
            or not isinstance(max_pages, int)
            or max_pages < 1
        ):
            raise ValueError("max_pages must be at least 1")
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= 20
        ):
            raise ValueError("page_size must be between 1 and 20")
        values = (keywords, radii, scoring_version)
        if all(value is None for value in values):
            return None
        if any(value is None for value in values):
            raise ValueError(
                "keywords, radii, and scoring_version must be provided together"
            )
        if keyword_classifications is None:
            raise ValueError(
                "keyword_classifications is required for signature-aware scope"
            )
        normalized_keywords = sorted(
            {keyword.strip() for keyword in keywords or () if keyword.strip()}
        )
        normalized_radii = sorted(
            {
                _canonical_number(radius, name="radius")
                for radius in radii or ()
            },
            key=Decimal,
        )
        normalized_mapping: dict[str, list[str]] = {}
        for keyword, classification in keyword_classifications.items():
            normalized_keyword = keyword.strip()
            if normalized_keyword in normalized_mapping:
                raise ValueError(
                    "duplicate normalized keyword_classifications key"
                )
            normalized_mapping[normalized_keyword] = _normalize_classifications(
                classification
            )
        if any(
            not keyword or not classification
            for keyword, classification in normalized_mapping.items()
        ):
            raise ValueError("keyword classifications cannot be empty")
        if set(normalized_mapping) != set(normalized_keywords):
            raise ValueError(
                "keyword_classifications must cover the normalized keyword set"
            )
        if (
            not normalized_keywords
            or not normalized_radii
            or not scoring_version.strip()
        ):
            raise ValueError("signature-aware query scope cannot be empty")
        signature_scope = {
            "provider": provider,
            "city": city,
            "category": category,
            "latitude": _canonical_number(latitude, name="latitude"),
            "longitude": _canonical_number(longitude, name="longitude"),
            "radius_meters": _canonical_number(
                radius_meters, name="radius_meters"
            ),
            "keywords": normalized_keywords,
            "radii": normalized_radii,
            "keyword_classifications": dict(sorted(normalized_mapping.items())),
            "scoring_version": scoring_version.strip(),
            "max_pages": _canonical_number(
                min(max_pages, ExternalContextSnapshotService.MAX_PAGES),
                name="max_pages",
            ),
            "page_size": _canonical_number(page_size, name="page_size"),
            "filter": filter,
            "scope": _canonical_number(scope, name="scope"),
            "coord_type": _canonical_number(coord_type, name="coord_type"),
            "radius_limit": radius_limit,
        }
        canonical = json.dumps(
            signature_scope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_number(value: object, *, name: str) -> str:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be numeric") from None
    if not number.is_finite():
        raise ValueError(f"{name} must be finite")
    normalized = format(number.normalize(), "f")
    return "0" if normalized in {"-0", "-0.0"} else normalized


def _normalize_classifications(value: object) -> list[str]:
    if isinstance(value, (str, bytes)) or hasattr(value, "value"):
        values = (value,)
    elif isinstance(value, (Sequence, set, frozenset)):
        values = value
    else:
        values = (value,)
    normalized = sorted(
        {
            str(getattr(item, "value", item)).strip()
            for item in values
            if str(getattr(item, "value", item)).strip()
        }
    )
    if not normalized:
        raise ValueError("keyword classifications cannot be empty")
    return normalized
