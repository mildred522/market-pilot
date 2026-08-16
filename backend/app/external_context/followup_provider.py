from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_runtime.contracts import FollowupEvidenceCapability
from app.agent_runtime.followup_evidence import (
    CapabilityEvidenceResult,
    EvidenceMaterial,
)
from app.db.models import ExternalContextSnapshot
from app.external_context.reference_repository import ReferenceDatasetRepository


class PersistedFollowupEvidenceProvider:
    def __init__(
        self,
        db: Session,
        *,
        project_id: int,
        reference_repository: ReferenceDatasetRepository | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._project_id = project_id
        self._references = reference_repository or ReferenceDatasetRepository()
        self._now = now or (lambda: datetime.now(UTC))

    def available_capabilities(
        self, project_profile: dict[str, Any]
    ) -> set[FollowupEvidenceCapability]:
        available: set[FollowupEvidenceCapability] = set()
        if project_profile.get("city") or project_profile.get("category"):
            available.add("external_industry_context")
        if self._latest_snapshot() is not None:
            available.add("location_competitors")
        return available

    def retrieve(
        self,
        capability: FollowupEvidenceCapability,
        project_profile: dict[str, Any],
    ) -> CapabilityEvidenceResult:
        if capability == "external_industry_context":
            return self._reference_context(project_profile)
        if capability == "location_competitors":
            return self._location_competitors()
        raise ValueError(f"unsupported persisted evidence capability: {capability}")

    def _reference_context(
        self, project_profile: dict[str, Any]
    ) -> CapabilityEvidenceResult:
        year = self._now().year - 1
        datasets = []
        for loader, raw_key in (
            (self._references.load_city, project_profile.get("city")),
            (self._references.load_category, project_profile.get("category")),
        ):
            if not isinstance(raw_key, str) or not raw_key.strip():
                continue
            try:
                datasets.append(loader(_reference_key(raw_key), year))
            except FileNotFoundError:
                continue
        if not datasets:
            raise LookupError("no matching city or category reference dataset")

        facts: list[EvidenceMaterial] = []
        for dataset in datasets:
            source_by_id = {source.source_id: source for source in dataset.sources}
            for metric_name, metric in dataset.metrics.items():
                sources = [source_by_id[item] for item in metric.source_ids]
                facts.append(
                    EvidenceMaterial(
                        canonical_ref=(
                            f"external.reference.{dataset.dataset_id}.metrics."
                            f"{metric_name}"
                        ),
                        source="external_context",
                        label=metric.definition or metric_name,
                        value=metric.value,
                        unit=metric.unit,
                        limitations=tuple(dataset.limitations[:8]),
                        provenance={
                            "dataset_id": dataset.dataset_id,
                            "period": metric.period,
                            "status": metric.status,
                            "published_at": dataset.published_at.isoformat(),
                            "sources": [
                                {
                                    "title": source.title,
                                    "publisher": source.publisher,
                                    "url": str(source.url),
                                }
                                for source in sources
                            ],
                        },
                    )
                )
            facts.append(
                EvidenceMaterial(
                    canonical_ref=f"external.reference.{dataset.dataset_id}.observations",
                    source="external_context",
                    label=f"{dataset.dataset_id}观察摘要",
                    value=dataset.observations,
                    limitations=tuple(dataset.limitations[:8]),
                    provenance={"dataset_id": dataset.dataset_id},
                )
            )
        return CapabilityEvidenceResult(
            capability="external_industry_context",
            status="completed",
            facts=tuple(facts),
        )

    def _location_competitors(self) -> CapabilityEvidenceResult:
        snapshot = self._latest_snapshot()
        if snapshot is None:
            raise LookupError("no persisted location competitor snapshot")
        facts = tuple(
            EvidenceMaterial(
                canonical_ref=(
                    f"external.location_snapshot.{snapshot.id}.metrics.{metric_name}"
                ),
                source="external_context",
                label=metric_name,
                value=value,
                limitations=tuple(snapshot.warnings_json[:8]),
                provenance={
                    "provider": snapshot.provider,
                    "city": snapshot.city,
                    "category": snapshot.category,
                    "radius_meters": snapshot.radius_meters,
                    "observed_at": snapshot.queried_at.isoformat(),
                    "expires_at": snapshot.expires_at.isoformat(),
                },
            )
            for metric_name, value in sorted(snapshot.metrics_json.items())
        )
        return CapabilityEvidenceResult(
            capability="location_competitors",
            status="completed",
            facts=facts,
        )

    def _latest_snapshot(self) -> ExternalContextSnapshot | None:
        return self._db.scalar(
            select(ExternalContextSnapshot)
            .where(ExternalContextSnapshot.project_id == self._project_id)
            .order_by(ExternalContextSnapshot.queried_at.desc())
            .limit(1)
        )


def _reference_key(value: str) -> str:
    return "-".join(value.strip().lower().split())
