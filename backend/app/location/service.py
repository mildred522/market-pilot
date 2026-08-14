from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
from sqlalchemy.orm import Session

from app.agent_runtime.contracts import CapabilityIntent
from app.db.models import LocationAnalysis
from app.tools.break_even_tool import calculate_break_even
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
from app.location.evidence import CONFIDENCE_FIELDS, LocationEvidenceBuilder

SCORING_VERSION = "location-v1"
SNAPSHOT_RADIUS_METERS = max(RING_RADII)


class LocationAnalysisService:
    @staticmethod
    def select_capability_mode(
        *,
        intent: CapabilityIntent,
        has_address: bool,
        has_coordinates: bool,
    ) -> Literal["manual", "recommendations"]:
        if intent == CapabilityIntent.ANALYZE_LOCATION:
            if has_address == has_coordinates:
                raise ValueError(
                    "manual location analysis requires one specific address or coordinates"
                )
            return "manual"
        if intent == CapabilityIntent.RECOMMEND_LOCATIONS:
            if has_address or has_coordinates:
                raise ValueError(
                    "location recommendation intent does not accept a specific location"
                )
            return "recommendations"
        raise ValueError("a validated location intent is required")

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
        self._evidence_builder = (
            evidence_builder
            if evidence_builder is not None
            else LocationEvidenceBuilder()
        )
        self._candidate_generator = candidate_generator
        self._references = (
            reference_repository
            if reference_repository is not None
            else ReferenceDatasetRepository()
        )
        self._screening_collector = (
            screening_collector
            if screening_collector is not None
            else BaiduCandidateScreeningCollector(baidu_client)
        )
        self._candidate_screener = (
            candidate_screener
            if candidate_screener is not None
            else CandidateScreener()
        )
        self._now = now if now is not None else lambda: datetime.now(UTC)

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
        planned_average_order_value: float | None = None,
        finance_assumptions: dict[str, Any] | None = None,
        finance_feasibility: FinanceFeasibility | None = None,
        radius_meters: int = SNAPSHOT_RADIUS_METERS,
    ) -> LocationAnalysis:
        if (
            isinstance(radius_meters, bool)
            or not isinstance(radius_meters, int)
            or not 300 <= radius_meters <= 5000
        ):
            raise ValueError("radius_meters must be between 300 and 5000")
        assessed_finance, finance_metrics = _assess_finance(
            planned_average_order_value=planned_average_order_value,
            assumptions=finance_assumptions,
        )
        try:
            return self._analyze_manual(
                project_id=project_id,
                city=city,
                category=category,
                latitude=latitude,
                longitude=longitude,
                finance_feasibility=finance_feasibility or assessed_finance,
                finance_metrics=finance_metrics,
                radius_meters=radius_meters,
                commit=True,
            )
        except Exception:
            self._session.rollback()
            raise

    def _analyze_manual(
        self,
        *,
        project_id: int,
        city: str,
        category: str,
        latitude: float,
        longitude: float,
        finance_feasibility: FinanceFeasibility,
        commit: bool,
        finance_metrics: dict[str, Any] | None = None,
        radius_meters: int = SNAPSHOT_RADIUS_METERS,
    ) -> LocationAnalysis:
        scope = self._scope(
            project_id=project_id,
            city=city,
            category=category,
            latitude=latitude,
            longitude=longitude,
            radius_meters=radius_meters,
        )
        snapshot = self._snapshots.find_reusable(self._session, **scope)
        warnings: list[str] = []
        if radius_meters < SNAPSHOT_RADIUS_METERS:
            unobserved = [
                radius for radius in RING_RADII if radius > radius_meters
            ]
            warnings.append(
                "radius coverage incomplete: unobserved outer rings "
                f"{unobserved}; low confidence due to partial radius coverage"
            )
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
                    max_radius_meters=radius_meters,
                )
            except BaiduMapResponseError as error:
                warning = self._provider_warning(error)
                if not error.retryable:
                    return self._persist(
                        mode="manual",
                        project_id=project_id,
                        input_scope={
                            **self._input_scope(city, category),
                            "radius_meters": radius_meters,
                        },
                        latitude=latitude,
                        longitude=longitude,
                        status="failed",
                        result_json=(
                            {
                                "finance_feasibility": finance_feasibility.value,
                                "finance_metrics": finance_metrics or {},
                            }
                            if finance_metrics
                            and finance_metrics.get("planned_average_order_value")
                            is not None
                            else {}
                        ),
                        warnings=[warning],
                        commit=commit,
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
                        finance_feasibility=finance_feasibility,
                        finance_metrics=finance_metrics or {},
                        commit=commit,
                        radius_meters=radius_meters,
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
                    commit=False,
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
            finance_metrics=finance_metrics or {},
            radius_meters=radius_meters,
        )
        self._verifier.verify(result, warnings=warnings)
        return self._persist(
            mode="manual",
            project_id=project_id,
            input_scope={
                **self._input_scope(city, category),
                "radius_meters": radius_meters,
            },
            latitude=latitude,
            longitude=longitude,
            status="degraded" if fallback or not complete else "completed",
            result=result,
            warnings=warnings,
            commit=commit,
        )

    def analyze_recommendations(
        self,
        *,
        project_id: int,
        city: str,
        region: str,
        category: str,
        max_candidates: int = 5,
        radius_meters: int = SNAPSHOT_RADIUS_METERS,
        planned_average_order_value: float | None = None,
        finance_assumptions: dict[str, Any] | None = None,
    ) -> LocationAnalysis:
        if (
            isinstance(max_candidates, bool)
            or not isinstance(max_candidates, int)
            or not 1 <= max_candidates <= 10
        ):
            raise ValueError("max_candidates must be between 1 and 10")
        if (
            isinstance(radius_meters, bool)
            or not isinstance(radius_meters, int)
            or not 300 <= radius_meters <= 5000
        ):
            raise ValueError("radius_meters must be between 300 and 5000")
        assessed_finance, finance_metrics = _assess_finance(
            planned_average_order_value=planned_average_order_value,
            assumptions=finance_assumptions,
        )
        try:
            analysis = self._analyze_recommendations(
                project_id=project_id,
                city=city,
                region=region,
                category=category,
                max_candidates=max_candidates,
                radius_meters=radius_meters,
                finance_feasibility=assessed_finance,
                finance_metrics=finance_metrics,
            )
            self._session.commit()
            self._session.refresh(analysis)
            return analysis
        except Exception:
            self._session.rollback()
            raise

    def _analyze_recommendations(
        self,
        *,
        project_id: int,
        city: str,
        region: str,
        category: str,
        max_candidates: int,
        radius_meters: int,
        finance_feasibility: FinanceFeasibility,
        finance_metrics: dict[str, Any],
    ) -> LocationAnalysis:
        generator = (
            self._candidate_generator
            if self._candidate_generator is not None
            else CandidateGenerator(self._baidu_client)
        )
        input_scope = {
            "city": city,
            "region": region,
            "category": category,
            "coordinate_system": "bd09ll",
            "max_candidates": max_candidates,
            "radius_meters": radius_meters,
            "planned_average_order_value": finance_metrics.get(
                "planned_average_order_value"
            ),
            "finance_assumptions": finance_metrics.get("assumptions"),
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
                commit=False,
            )

        # Full screening costs three provider calls per candidate. Pre-rank
        # anchor clusters and keep a bounded exploration pool so requesting a
        # few recommendations does not screen every generated cluster.
        screening_pool = generator.screen(generated)[: max_candidates * 2]

        screened, warnings, screening_failures = self._screen_candidates(
            screening_pool, radius_meters=radius_meters
        )
        # Deep analysis is substantially more expensive than screening. Only
        # analyze the number of candidates the caller can actually receive.
        screened = screened[:max_candidates]
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
                commit=False,
            )
        candidate_results: list[dict[str, Any]] = []
        child_degraded = False
        child_failed = False
        for screened_candidate in screened:
            candidate = screened_candidate.candidate
            analysis = self._analyze_manual(
                project_id=project_id,
                city=city,
                category=category,
                latitude=candidate.latitude,
                longitude=candidate.longitude,
                finance_feasibility=finance_feasibility,
                finance_metrics=finance_metrics,
                radius_meters=radius_meters,
                commit=False,
            )
            warnings.extend(
                f"{candidate.name}:{warning}"
                for warning in analysis.warnings_json
            )
            if analysis.status == "failed":
                child_failed = True
                continue
            if analysis.status == "degraded":
                child_degraded = True
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
        insufficient_candidates = len(selected) < max_candidates
        status = (
            "failed"
            if not selected
            else "degraded"
            if (
                child_degraded
                or child_failed
                or bool(screening_failures)
                or insufficient_candidates
            )
            else "completed"
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
                "candidate_count": len(selected),
                "candidates": selected,
            },
            evidence_json=[
                evidence
                for candidate in selected
                for evidence in candidate["evidence"]
            ],
            warnings=warnings,
            commit=False,
        )

    def _screen_candidates(
        self, candidates, *, radius_meters: int
    ) -> tuple[list[ScreenedCandidate], list[str], list[bool]]:
        screened: list[ScreenedCandidate] = []
        warnings: list[str] = []
        retryable_failures: list[bool] = []
        for candidate in candidates:
            identifier = candidate.representative.uid
            try:
                metrics = self._screening_collector.collect(
                    candidate=candidate,
                    radius_meters=radius_meters,
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
        finance_feasibility: FinanceFeasibility,
        finance_metrics: dict[str, Any],
        commit: bool,
        radius_meters: int = SNAPSHOT_RADIUS_METERS,
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
        scope = {
            "city": city,
            "category": category,
            "year": year,
            "center": {"latitude": latitude, "longitude": longitude},
            "radius_meters": radius_meters,
        }
        observed_at = self._now()
        expires_at = observed_at + timedelta(days=1)
        dimensions = DimensionScores(
            competition_balance=0,
            demand_proxies=0,
            transit=0,
            price_fit=0,
            surrounding_synergy=0,
        )
        confidence_inputs = ConfidenceInputs(
            pagination=0,
            key_fields=0,
            keyword_coverage=0,
            freshness=0,
            status_comment_coverage=0,
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
                    "score": getattr(dimensions, label),
                    "local_poi_data": "unavailable",
                    "dataset_ids": dataset_ids,
                },
            )
            for label in labels
        ]
        evidence.extend(
            Evidence(
                source="reference_dataset",
                label=f"confidence.{label}",
                observed_at=observed_at,
                expires_at=expires_at,
                query_scope=scope,
                value=getattr(confidence_inputs, label),
            )
            for label in CONFIDENCE_FIELDS
        )
        result = self._scorer.score(
            dimensions,
            confidence_inputs,
            finance_feasibility=finance_feasibility,
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
        result = result.model_copy(
            update={"evidence": final_evidence, "finance_metrics": finance_metrics}
        )
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
            input_scope={
                **self._input_scope(city, category),
                "radius_meters": radius_meters,
            },
            latitude=latitude,
            longitude=longitude,
            status="degraded",
            result=result,
            warnings=all_warnings,
            commit=commit,
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
        finance_metrics: dict[str, Any],
        radius_meters: int,
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
            radius_meters=radius_meters,
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
        return result.model_copy(
            update={"evidence": final_evidence, "finance_metrics": finance_metrics}
        )

    def _save_snapshot(
        self,
        *,
        scope: dict[str, Any],
        pois: Sequence[NormalizedPoiFeature],
        observed_at: datetime,
        expires_at: datetime,
        warnings: list[str],
        commit: bool,
    ) -> None:
        evidence = EvidenceRecord(
            source="baidu_map",
            label="normalized POI collection",
            observed_at=observed_at,
            expires_at=expires_at,
            scope={
                "latitude": scope["latitude"],
                "longitude": scope["longitude"],
                "radius_meters": scope["radius_meters"],
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
            commit=commit,
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
        radius_meters: int = SNAPSHOT_RADIUS_METERS,
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
            "radius_meters": radius_meters,
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
        commit: bool = True,
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
        if commit:
            self._session.commit()
            self._session.refresh(analysis)
        else:
            self._session.flush()
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


def _assess_finance(
    *,
    planned_average_order_value: float | None,
    assumptions: dict[str, Any] | None,
) -> tuple[FinanceFeasibility, dict[str, Any]]:
    metrics: dict[str, Any] = {
        "planned_average_order_value": planned_average_order_value,
        "assumptions": assumptions,
    }
    if not assumptions or planned_average_order_value is None:
        return FinanceFeasibility.MISSING, metrics

    required = (
        "gross_margin",
        "labor_cost",
        "utilities_cost",
        "other_fixed_cost",
        "target_daily_orders",
    )
    if any(assumptions.get(key) is None for key in required):
        return FinanceFeasibility.MISSING, metrics

    gross_margin = float(assumptions["gross_margin"])
    target_daily_orders = int(assumptions["target_daily_orders"])
    if gross_margin <= 0 or target_daily_orders <= 0:
        return FinanceFeasibility.INFEASIBLE, metrics

    planned_daily_revenue = round(
        target_daily_orders * planned_average_order_value, 2
    )
    planned_daily_gross_profit = round(
        planned_daily_revenue * gross_margin, 2
    )
    monthly_non_rent = sum(float(assumptions[key]) for key in required[1:4])
    max_monthly_rent = round(
        max(0, planned_daily_gross_profit - monthly_non_rent / 30) * 30,
        2,
    )
    metrics.update(
        {
            "planned_daily_revenue": planned_daily_revenue,
            "planned_daily_gross_profit": planned_daily_gross_profit,
            "max_plannable_monthly_rent": max_monthly_rent,
            "monthly_non_rent_fixed_cost": round(monthly_non_rent, 2),
            "disclaimer": "Planning model only; it does not observe traffic, revenue, or rent.",
        }
    )

    monthly_rent = assumptions.get("monthly_rent")
    if monthly_rent is None:
        return FinanceFeasibility.ADJUSTABLE, metrics

    break_even = calculate_break_even(
        monthly_rent=float(monthly_rent),
        monthly_labor=float(assumptions["labor_cost"]),
        monthly_utilities=float(assumptions["utilities_cost"]),
        monthly_misc=float(assumptions["other_fixed_cost"]),
        gross_margin=gross_margin,
        avg_order_value=planned_average_order_value,
    )
    metrics["break_even"] = break_even
    daily_fixed_cost = float(break_even["daily_fixed_cost"])
    surplus = planned_daily_gross_profit - daily_fixed_cost
    if surplus >= 0:
        return FinanceFeasibility.FEASIBLE, metrics
    if surplus >= -planned_daily_gross_profit * 0.2:
        return FinanceFeasibility.ADJUSTABLE, metrics
    return FinanceFeasibility.INFEASIBLE, metrics
