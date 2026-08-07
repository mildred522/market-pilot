from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.db.models import LocationAnalysis
from app.external_context.baidu_client import BaiduMapResponseError
from app.external_context.contracts import EvidenceRecord, ExternalContextData
from app.external_context.reference_repository import ReferenceDatasetRepository
from app.location.collector import (
    DEFAULT_COMPETITOR_KEYWORD_GROUPS,
    RING_RADII,
)
from app.location.candidates import (
    BaiduCandidateScreeningCollector,
    CandidateGenerator,
    CandidateScreener,
    ScreenedCandidate,
)
from app.location.contracts import (
    ConfidenceInputs,
    DimensionScores,
    Evidence,
    FinanceFeasibility,
    LocationAnalysisResult,
    NormalizedPoiFeature,
)
from app.location.evidence import LocationEvidenceBuilder

SCORING_VERSION = "location-v1"
SNAPSHOT_RADIUS_METERS = max(RING_RADII)


class LocationAnalysisService:
    def __init__(
        self,
        *,
        session: Session,
        baidu_client,
        poi_collector,
        feature_builder,
        scorer,
        snapshot_service,
        evidence_verifier,
        evidence_builder=None,
        candidate_generator=None,
        reference_repository=None,
        screening_collector=None,
        candidate_screener=None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._baidu_client = baidu_client
        self._collector = poi_collector
        self._feature_builder = feature_builder
        self._scorer = scorer
        self._snapshots = snapshot_service
        self._verifier = evidence_verifier
        self._evidence_builder = evidence_builder or LocationEvidenceBuilder()
        self._candidate_generator = candidate_generator
        self._references = reference_repository or ReferenceDatasetRepository()
        self._screening_collector = (
            screening_collector or BaiduCandidateScreeningCollector(baidu_client)
        )
        self._candidate_screener = candidate_screener or CandidateScreener()
        self._now = now or (lambda: datetime.now(UTC))

    def get_analysis(self, analysis_id: int) -> LocationAnalysis | None:
        return self._session.get(LocationAnalysis, analysis_id)

    def analyze_manual(
        self,
        *,
        project_id: int,
        city: str,
        category: str,
        latitude: float,
        longitude: float,
        finance_feasibility: FinanceFeasibility = FinanceFeasibility.MISSING,
    ) -> LocationAnalysis:
        scope = self._scope(
            project_id=project_id,
            city=city,
            category=category,
            latitude=latitude,
            longitude=longitude,
        )
        snapshot = self._snapshots.find_reusable(self._session, **scope)
        warnings: list[str] = []
        fallback = False
        if snapshot is not None:
            pois = self._snapshot_pois(snapshot)
            observed_at = _aware(snapshot.queried_at)
            expires_at = _aware(snapshot.expires_at)
            warnings.append(f"snapshot reuse:id={snapshot.id}")
            complete = not snapshot.warnings_json
        else:
            try:
                collection = self._collector.collect_competitors(
                    latitude=latitude,
                    longitude=longitude,
                )
            except BaiduMapResponseError as error:
                warning = self._provider_warning(error)
                if not error.retryable:
                    return self._persist(
                        mode="manual",
                        project_id=project_id,
                        input_scope=self._input_scope(city, category),
                        latitude=latitude,
                        longitude=longitude,
                        status="failed",
                        warnings=[warning],
                    )
                warnings.append(warning)
                snapshot = self._snapshots.find_latest_stale(
                    self._session, **scope
                )
                if snapshot is None:
                    return self._reference_fallback(
                        project_id=project_id,
                        city=city,
                        category=category,
                        latitude=latitude,
                        longitude=longitude,
                        warnings=warnings,
                    )
                pois = self._snapshot_pois(snapshot)
                observed_at = _aware(snapshot.queried_at)
                expires_at = _aware(snapshot.expires_at)
                warnings.append(
                    "stale snapshot fallback:"
                    f"id={snapshot.id},expired_at={expires_at.isoformat()}"
                )
                complete = False
                fallback = True
            else:
                pois = list(collection)
                observed_at = self._now()
                expires_at = observed_at + timedelta(days=7)
                complete = collection.complete
                warnings.extend(collection.warnings)
                self._save_snapshot(
                    scope=scope,
                    pois=pois,
                    observed_at=observed_at,
                    expires_at=expires_at,
                    warnings=list(collection.warnings),
                )

        result = self._analyze_pois(
            pois=pois,
            city=city,
            category=category,
            latitude=latitude,
            longitude=longitude,
            observed_at=observed_at,
            expires_at=expires_at,
            complete=complete,
            fallback=fallback,
            finance_feasibility=finance_feasibility,
        )
        self._verifier.verify(result, warnings=warnings)
        return self._persist(
            mode="manual",
            project_id=project_id,
            input_scope=self._input_scope(city, category),
            latitude=latitude,
            longitude=longitude,
            status="degraded" if fallback or not complete else "completed",
            result=result,
            warnings=warnings,
        )

    def analyze_recommendations(
        self,
        *,
        project_id: int,
        city: str,
        region: str,
        category: str,
        max_candidates: int = 5,
    ) -> LocationAnalysis:
        if not 3 <= max_candidates <= 5:
            raise ValueError("max_candidates must be between 3 and 5")
        generator = self._candidate_generator or CandidateGenerator(
            self._baidu_client
        )
        input_scope = {
            "city": city,
            "region": region,
            "category": category,
            "coordinate_system": "bd09ll",
            "max_candidates": max_candidates,
        }
        try:
            generated = generator.generate(region=region)
        except BaiduMapResponseError as error:
            return self._persist(
                mode="recommendations",
                project_id=project_id,
                input_scope=input_scope,
                latitude=None,
                longitude=None,
                status="failed",
                warnings=[self._provider_warning(error)],
            )

        screened, warnings, screening_failures = self._screen_candidates(
            generated
        )
        screened = screened[:10]
        if not screened and screening_failures:
            status = (
                "degraded"
                if any(screening_failures)
                else "failed"
            )
            warnings.append(
                f"insufficient candidates: requested {max_candidates}, available 0"
            )
            return self._persist(
                mode="recommendations",
                project_id=project_id,
                input_scope=input_scope,
                latitude=None,
                longitude=None,
                status=status,
                result_json={
                    "region": region,
                    "candidate_count": 0,
                    "candidates": [],
                },
                warnings=warnings,
            )
        candidate_results: list[dict[str, Any]] = []
        for screened_candidate in screened:
            candidate = screened_candidate.candidate
            analysis = self.analyze_manual(
                project_id=project_id,
                city=city,
                category=category,
                latitude=candidate.latitude,
                longitude=candidate.longitude,
            )
            if analysis.status == "failed":
                warnings.extend(
                    f"{candidate.name}:{warning}"
                    for warning in analysis.warnings_json
                )
                continue
            candidate_results.append(
                {
                    "name": candidate.name,
                    "center": {
                        "latitude": candidate.latitude,
                        "longitude": candidate.longitude,
                    },
                    "transition_input": {
                        "latitude": candidate.latitude,
                        "longitude": candidate.longitude,
                        "coordinate_system": "bd09ll",
                    },
                    "representative_anchor": {
                        "uid": candidate.representative.uid,
                        "name": candidate.representative.name,
                        "anchor_type": candidate.representative.anchor_type,
                    },
                    "merged_anchor_evidence": [
                        {
                            "uid": item.uid,
                            "name": item.name,
                            "anchor_type": item.anchor_type,
                        }
                        for item in candidate.anchors
                    ],
                    "analysis_id": analysis.id,
                    "screening": {
                        "score": screened_candidate.score,
                        "demand_proxies": (
                            screened_candidate.metrics.demand_proxies
                        ),
                        "competitors": screened_candidate.metrics.competitors,
                        "transit": screened_candidate.metrics.transit,
                    },
                    "status": analysis.status,
                    "result": analysis.result_json,
                    "evidence": analysis.evidence_json,
                    "warnings": analysis.warnings_json,
                }
            )
        candidate_results.sort(key=_candidate_result_key)
        selected = candidate_results[:max_candidates]
        if len(selected) < max_candidates:
            warnings.append(
                f"insufficient candidates: requested {max_candidates}, "
                f"available {len(selected)}"
            )
        return self._persist(
            mode="recommendations",
            project_id=project_id,
            input_scope=input_scope,
            latitude=None,
            longitude=None,
            status="degraded" if warnings else "completed",
            result_json={
                "region": region,
                "candidate_count": len(selected),
                "candidates": selected,
            },
            evidence_json=[
                evidence
                for candidate in selected
                for evidence in candidate["evidence"]
            ],
            warnings=warnings,
        )

    def _screen_candidates(
        self, candidates
    ) -> tuple[list[ScreenedCandidate], list[str], list[bool]]:
        screened: list[ScreenedCandidate] = []
        warnings: list[str] = []
        retryable_failures: list[bool] = []
        for candidate in candidates:
            identifier = candidate.representative.uid
            try:
                metrics = self._screening_collector.collect(
                    candidate=candidate,
                    radius_meters=self._candidate_screener.RADIUS_METERS,
                    queries=self._candidate_screener.QUERIES,
                )
            except BaiduMapResponseError as error:
                warnings.append(
                    f"candidate_screening:{identifier}:"
                    f"{self._provider_warning(error)}"
                )
                retryable_failures.append(error.retryable)
            except httpx.TransportError:
                warnings.append(
                    f"candidate_screening:{identifier}:"
                    "baidu_map:transport:retryable"
                )
                retryable_failures.append(True)
            else:
                screened.append(
                    ScreenedCandidate(
                        candidate=candidate,
                        score=self._candidate_screener.score(metrics),
                        metrics=metrics,
                    )
                )
        screened.sort(
            key=lambda item: (
                -item.score,
                item.candidate.representative.uid,
                item.candidate.representative.name,
                item.candidate.latitude,
                item.candidate.longitude,
            )
        )
        return screened, warnings, retryable_failures

    def _reference_fallback(
        self,
        *,
        project_id: int,
        city: str,
        category: str,
        latitude: float,
        longitude: float,
        warnings: list[str],
    ) -> LocationAnalysis:
        year = self._now().year - 1
        datasets = []
        for loader, key in (
            (self._references.load_city, _reference_key(city)),
            (self._references.load_category, _reference_key(category)),
        ):
            try:
                datasets.append(loader(key, year))
            except (FileNotFoundError, ValueError):
                continue
        dataset_ids = sorted(dataset.dataset_id for dataset in datasets)
        reference_value = {
            "dataset_ids": dataset_ids,
            "metrics": {
                dataset.dataset_id: {
                    name: metric.model_dump(mode="json")
                    for name, metric in dataset.metrics.items()
                }
                for dataset in datasets
            },
            "local_poi_data": "unavailable",
        }
        scope = {"city": city, "category": category, "year": year}
        observed_at = self._now()
        expires_at = observed_at + timedelta(days=1)
        dimensions = DimensionScores(
            competition_balance=0,
            demand_proxies=0,
            transit=0,
            price_fit=0,
            surrounding_synergy=0,
        )
        labels = (
            "competition_balance",
            "demand_proxies",
            "transit",
            "price_fit",
            "surrounding_synergy",
        )
        evidence = [
            Evidence(
                source="reference_dataset",
                label=f"dimension.{label}",
                observed_at=observed_at,
                expires_at=expires_at,
                query_scope=scope,
                value={
                    "local_poi_data": "unavailable",
                    "dataset_ids": dataset_ids,
                },
            )
            for label in labels
        ]
        result = self._scorer.score(
            dimensions,
            ConfidenceInputs(
                pagination=0,
                key_fields=0,
                keyword_coverage=0,
                freshness=0,
                status_comment_coverage=0,
            ),
            finance_feasibility=FinanceFeasibility.MISSING,
            evidence=evidence,
        )
        final_evidence = [
            *evidence,
            evidence[0].model_copy(
                update={"label": "conclusion", "value": result.conclusion}
            ),
            evidence[0].model_copy(
                update={"label": "fallback", "value": reference_value}
            ),
        ]
        result = result.model_copy(update={"evidence": final_evidence})
        reference_warning = (
            f"reference fallback:datasets={','.join(dataset_ids)}"
            if dataset_ids
            else "reference fallback:unavailable"
        )
        all_warnings = [*warnings, reference_warning]
        self._verifier.verify(result, warnings=all_warnings)
        return self._persist(
            mode="manual",
            project_id=project_id,
            input_scope=self._input_scope(city, category),
            latitude=latitude,
            longitude=longitude,
            status="degraded",
            result=result,
            warnings=all_warnings,
        )

    def _analyze_pois(
        self,
        *,
        pois: Sequence[NormalizedPoiFeature],
        city: str,
        category: str,
        latitude: float,
        longitude: float,
        observed_at: datetime,
        expires_at: datetime,
        complete: bool,
        fallback: bool,
        finance_feasibility: FinanceFeasibility,
    ) -> LocationAnalysisResult:
        features = self._feature_builder.build(pois)
        dimensions, confidence, evidence = self._evidence_builder.build(
            features=features,
            city=city,
            category=category,
            latitude=latitude,
            longitude=longitude,
            observed_at=observed_at,
            expires_at=expires_at,
            complete=complete,
            fallback=fallback,
        )
        result = self._scorer.score(
            dimensions,
            confidence,
            finance_feasibility=finance_feasibility,
            evidence=evidence,
        )
        conclusion = evidence[0].model_copy(
            update={"label": "conclusion", "value": result.conclusion}
        )
        final_evidence = [*evidence, conclusion]
        if fallback or result.confidence_score < 60:
            final_evidence.append(
                evidence[0].model_copy(
                    update={"label": "fallback", "value": "low confidence or snapshot"}
                )
            )
        return result.model_copy(update={"evidence": final_evidence})

    def _save_snapshot(
        self,
        *,
        scope: dict[str, Any],
        pois: Sequence[NormalizedPoiFeature],
        observed_at: datetime,
        expires_at: datetime,
        warnings: list[str],
    ) -> None:
        evidence = EvidenceRecord(
            source="baidu_map",
            label="normalized POI collection",
            observed_at=observed_at,
            expires_at=expires_at,
            scope={
                "latitude": scope["latitude"],
                "longitude": scope["longitude"],
                "radius_meters": SNAPSHOT_RADIUS_METERS,
            },
            value={"poi_count": len(pois)},
        )
        save_scope = {key: value for key, value in scope.items() if key != "now"}
        self._snapshots.save(
            self._session,
            **save_scope,
            queried_at=observed_at,
            context=ExternalContextData(
                metrics={
                    "pois": [item.model_dump(mode="json") for item in pois]
                },
                evidence=[evidence],
                warnings=warnings,
            ),
        )

    @staticmethod
    def _snapshot_pois(snapshot) -> list[NormalizedPoiFeature]:
        return [
            NormalizedPoiFeature.model_validate(item)
            for item in snapshot.metrics_json.get("pois", [])
        ]

    def _scope(
        self,
        *,
        project_id: int,
        city: str,
        category: str,
        latitude: float,
        longitude: float,
    ) -> dict[str, Any]:
        keyword_classifications = {
            keyword: group.classification.value
            for group in DEFAULT_COMPETITOR_KEYWORD_GROUPS
            for keyword in group.keywords
        }
        return {
            "project_id": project_id,
            "provider": "baidu_map",
            "city": city,
            "category": category,
            "latitude": latitude,
            "longitude": longitude,
            "radius_meters": SNAPSHOT_RADIUS_METERS,
            "now": self._now(),
            "keywords": tuple(keyword_classifications),
            "radii": RING_RADII,
            "keyword_classifications": keyword_classifications,
            "scoring_version": SCORING_VERSION,
        }

    @staticmethod
    def _input_scope(city: str, category: str) -> dict[str, str]:
        return {"city": city, "category": category, "coordinate_system": "bd09ll"}

    @staticmethod
    def _provider_warning(error: BaiduMapResponseError) -> str:
        retryability = "retryable" if error.retryable else "permanent"
        return f"baidu_map:{error.kind.value}:{retryability}"

    def _persist(
        self,
        *,
        mode: str,
        project_id: int,
        input_scope: dict[str, Any],
        latitude: float | None,
        longitude: float | None,
        status: str,
        result: LocationAnalysisResult | None = None,
        result_json: dict[str, Any] | None = None,
        evidence_json: list[dict[str, Any]] | None = None,
        warnings: Sequence[str] = (),
    ) -> LocationAnalysis:
        serialized_result = (
            result.model_dump(mode="json") if result is not None else result_json or {}
        )
        serialized_evidence = (
            [item.model_dump(mode="json") for item in result.evidence]
            if result is not None
            else evidence_json or []
        )
        analysis = LocationAnalysis(
            mode=mode,
            project_id=project_id,
            input_scope_json=input_scope,
            center_latitude=latitude,
            center_longitude=longitude,
            status=status,
            result_json=serialized_result,
            evidence_json=serialized_evidence,
            warnings_json=list(warnings),
        )
        self._session.add(analysis)
        self._session.commit()
        self._session.refresh(analysis)
        return analysis


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _reference_key(value: str) -> str:
    return "-".join(value.strip().lower().split())


def _candidate_result_key(item: dict[str, Any]) -> tuple[Any, ...]:
    result = item["result"]
    center = item["center"]
    return (
        -result["opportunity_score"],
        -result["confidence_score"],
        item["name"],
        center["latitude"],
        center["longitude"],
    )
