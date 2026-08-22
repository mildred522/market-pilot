from collections.abc import Callable
from math import isfinite
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.models import LocationAnalysis, Project
from app.db.session import get_db
from app.external_context.baidu_client import (
    BaiduGeocodeResult,
    BaiduMapConfigurationError,
    BaiduMapResponseError,
)
from app.external_context.factory import get_location_provider_factory
from app.external_context.provider import LocationProvider
from app.external_context.snapshot_service import ExternalContextSnapshotService
from app.location.collector import PoiCollector
from app.location.evidence import EvidenceVerificationError, LocationEvidenceVerifier
from app.location.feature_builder import LocationFeatureBuilder
from app.location.contracts import LocationAnalysisResult
from app.location.scorer import LocationScorer
from app.location.service import LocationAnalysisService

from app.schemas.location import (
    Coordinate,
    ConfidenceSummary,
    FinanceSummary,
    LocationAnalysisResponse,
    LocationRecommendationsRequest,
    LocationSuggestionsResponse,
    ManualLocationAnalysisRequest,
    OpportunitySummary,
    RecommendationCandidate,
)

router = APIRouter(prefix="/pre-open/location", tags=["location"])


def get_baidu_client_factory() -> Callable[[], LocationProvider]:
    return get_location_provider_factory()


def get_location_service_factory() -> Callable[[Session, LocationProvider], LocationAnalysisService]:
    def factory(db: Session, baidu_client: LocationProvider) -> LocationAnalysisService:
        return LocationAnalysisService(
            session=db,
            baidu_client=baidu_client,
            poi_collector=PoiCollector(baidu_client),
            feature_builder=LocationFeatureBuilder(),
            scorer=LocationScorer(),
            snapshot_service=ExternalContextSnapshotService(),
            evidence_verifier=LocationEvidenceVerifier(),
        )

    return factory


def get_location_evidence_verifier() -> LocationEvidenceVerifier:
    return LocationEvidenceVerifier()


@router.get("/suggestions", response_model=LocationSuggestionsResponse)
def location_suggestions(
    kind: Literal["city", "district"],
    query: str = Query(default="", max_length=80),
    city: str | None = Query(default=None, min_length=1, max_length=80),
    client_factory: Callable[[], LocationProvider] = Depends(get_baidu_client_factory),
) -> LocationSuggestionsResponse:
    normalized_query = query.strip()
    if kind == "city" and not normalized_query:
        return LocationSuggestionsResponse()
    if kind == "district" and not city:
        raise _structured_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "city_required",
            "city is required for district suggestions",
        )
    try:
        suggestions = client_factory().suggest_places(
            query=normalized_query or "区政府",
            region="全国" if kind == "city" else str(city).strip(),
            city_limit=kind == "district",
        )
        values = (
            (item.city for item in suggestions)
            if kind == "city"
            else (item.district for item in suggestions)
        )
        return LocationSuggestionsResponse(
            options=list(dict.fromkeys(value for value in values if value))
        )
    except BaiduMapConfigurationError as error:
        raise _structured_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "baidu_configuration_error",
            "Baidu map configuration is unavailable",
        ) from error
    except BaiduMapResponseError as error:
        raise _provider_http_error(error) from error


@router.post("/manual-analysis", response_model=LocationAnalysisResponse)
def manual_analysis(
    payload: ManualLocationAnalysisRequest,
    db: Session = Depends(get_db),
    client_factory: Callable[[], LocationProvider] = Depends(get_baidu_client_factory),
    service_factory: Callable[[Session, LocationProvider], LocationAnalysisService] = Depends(
        get_location_service_factory
    ),
) -> LocationAnalysisResponse:
    _require_project(db, payload.project_id)
    try:
        client = client_factory()
        source = "bd09_input"
        if payload.address is not None:
            geocoded = client.geocode(address=payload.address, city=payload.city)
            latitude, longitude = _coordinate_values(geocoded)
            source = (
                getattr(geocoded, "source", None)
                if not isinstance(geocoded, dict)
                else geocoded.get("source")
            ) or "baidu_geocoding"
        else:
            latitude, longitude = payload.latitude, payload.longitude
        analysis = service_factory(db, client).analyze_manual(
            project_id=payload.project_id,
            city=payload.city,
            category=payload.category,
            latitude=latitude,
            longitude=longitude,
            planned_average_order_value=payload.planned_average_order_value,
            finance_assumptions=(
                payload.finance_assumptions.model_dump(mode="json")
                if payload.finance_assumptions
                else None
            ),
            radius_meters=payload.radius_meters,
        )
        _raise_for_provider_warnings(analysis.warnings_json)
        return _response_for_row(analysis, source=source, request=payload)
    except BaiduMapConfigurationError as error:
        raise _structured_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "baidu_configuration_error",
            "Baidu map configuration is unavailable",
        ) from error
    except BaiduMapResponseError as error:
        raise _provider_http_error(error) from error
    except EvidenceVerificationError as error:
        raise _structured_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "evidence_verification_failed",
            str(error),
        ) from error
    except ValueError as error:
        raise _structured_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "validation_error", str(error)) from error


@router.post("/recommendations", response_model=LocationAnalysisResponse)
def recommendations(
    payload: LocationRecommendationsRequest,
    db: Session = Depends(get_db),
    client_factory: Callable[[], LocationProvider] = Depends(get_baidu_client_factory),
    service_factory: Callable[[Session, LocationProvider], LocationAnalysisService] = Depends(
        get_location_service_factory
    ),
) -> LocationAnalysisResponse:
    _require_project(db, payload.project_id)
    try:
        client = client_factory()
        analysis = service_factory(db, client).analyze_recommendations(
            project_id=payload.project_id,
            city=payload.city,
            region=payload.district,
            category=payload.category,
            max_candidates=payload.candidate_count,
            radius_meters=payload.radius_meters,
            planned_average_order_value=payload.planned_average_order_value,
            finance_assumptions=(
                payload.finance_assumptions.model_dump(mode="json")
                if payload.finance_assumptions
                else None
            ),
        )
        _raise_for_provider_warnings(analysis.warnings_json)
        return _response_for_row(analysis, request=payload)
    except BaiduMapConfigurationError as error:
        raise _structured_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "baidu_configuration_error",
            "Baidu map configuration is unavailable",
        ) from error
    except BaiduMapResponseError as error:
        raise _provider_http_error(error) from error
    except EvidenceVerificationError as error:
        raise _structured_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "evidence_verification_failed", str(error)) from error
    except ValueError as error:
        raise _structured_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "validation_error", str(error)) from error


@router.get("/analyses/{analysis_id}", response_model=LocationAnalysisResponse)
def get_location_analysis(
    analysis_id: int,
    db: Session = Depends(get_db),
    verifier: LocationEvidenceVerifier = Depends(get_location_evidence_verifier),
) -> LocationAnalysisResponse:
    analysis = db.get(LocationAnalysis, analysis_id)
    if analysis is None:
        raise _structured_error(status.HTTP_404_NOT_FOUND, "analysis_not_found", "location analysis not found")
    try:
        _verify_persisted_analysis(analysis, verifier)
        return _response_for_row(analysis)
    except EvidenceVerificationError as error:
        raise _structured_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "evidence_verification_failed",
            str(error),
        ) from error


def _require_project(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise _structured_error(status.HTTP_404_NOT_FOUND, "project_not_found", "project not found")
    return project


def _coordinate_values(value: BaiduGeocodeResult | dict[str, Any]) -> tuple[float, float]:
    try:
        latitude, longitude = (
            (float(value["latitude"]), float(value["longitude"]))
            if isinstance(value, dict)
            else (float(value.latitude), float(value.longitude))
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        raise BaiduMapResponseError(
            "Baidu geocoding returned invalid coordinates",
            kind="request",
        ) from None
    if not isfinite(latitude) or not -90 <= latitude <= 90:
        raise BaiduMapResponseError(
            "Baidu geocoding returned an invalid latitude",
            kind="request",
        )
    if not isfinite(longitude) or not -180 <= longitude <= 180:
        raise BaiduMapResponseError(
            "Baidu geocoding returned an invalid longitude",
            kind="request",
        )
    return latitude, longitude


def _verify_persisted_analysis(
    row: LocationAnalysis, verifier: LocationEvidenceVerifier
) -> None:
    if row.mode == "recommendations":
        for candidate in (row.result_json or {}).get("candidates", []):
            result = dict(candidate.get("result") or {})
            result["evidence"] = candidate.get("evidence") or []
            try:
                normalized = LocationAnalysisResult.model_validate(result)
            except ValidationError as error:
                raise EvidenceVerificationError(
                    f"invalid persisted candidate result: {error}"
                ) from error
            verifier.verify(normalized, warnings=candidate.get("warnings") or [])
        return
    result = dict(row.result_json or {})
    result["evidence"] = row.evidence_json or []
    try:
        normalized = LocationAnalysisResult.model_validate(result)
    except ValidationError as error:
        raise EvidenceVerificationError(
            f"invalid persisted analysis result: {error}"
        ) from error
    verifier.verify(normalized, warnings=row.warnings_json or [])


def _response_for_row(
    row: LocationAnalysis,
    *,
    source: str | None = None,
    request: ManualLocationAnalysisRequest | LocationRecommendationsRequest | None = None,
) -> LocationAnalysisResponse:
    result = row.result_json or {}
    scope = dict(row.input_scope_json or {})
    if request is not None:
        scope.update(
            {
                "district": request.district,
                "target_customer": request.target_customer,
                "planned_average_order_value": request.planned_average_order_value,
                "finance_assumptions": request.finance_assumptions.model_dump(mode="json")
                if request.finance_assumptions
                else None,
            }
        )
    center = None
    if row.center_latitude is not None and row.center_longitude is not None:
        center = Coordinate(
            latitude=row.center_latitude,
            longitude=row.center_longitude,
            source=source or scope.get("location_source"),
        )
    if row.mode == "recommendations":
        candidates = [_candidate_response(item) for item in result.get("candidates", [])]
        return LocationAnalysisResponse(
            mode=row.mode,
            status=row.status,
            analysis_id=row.id,
            input_scope=scope,
            center=None,
            opportunity=OpportunitySummary(),
            confidence=ConfidenceSummary(),
            finance=FinanceSummary(),
            evidence=row.evidence_json or [],
            warnings=row.warnings_json or [],
            risks=_risks({}, row.warnings_json or []),
            recommendations=_recommendations(),
            candidates=candidates,
        )
    return _result_response(
        mode=row.mode,
        status=row.status,
        analysis_id=row.id,
        input_scope=scope,
        center=center,
        result=result,
        evidence=row.evidence_json or [],
        warnings=row.warnings_json or [],
    )


def _candidate_response(item: dict[str, Any]) -> RecommendationCandidate:
    result = item.get("result") or {}
    center_data = item.get("center") or {}
    center = Coordinate(**center_data, source="recommendation")
    return RecommendationCandidate(
        name=item.get("name", "candidate"),
        center=center,
        transition_coordinates=Coordinate(**center_data, source="recommendation"),
        opportunity=OpportunitySummary(
            score=result.get("opportunity_score"), conclusion=result.get("conclusion")
        ),
        confidence=ConfidenceSummary(score=result.get("confidence_score")),
        finance=FinanceSummary(
            feasibility=result.get("finance_feasibility"),
            assumptions_provided=bool((result.get("finance_metrics") or {}).get("assumptions")),
            metrics=result.get("finance_metrics") or {},
        ),
        dimension_breakdown=result.get("dimension_scores") or {},
        confidence_breakdown=result.get("confidence") or {},
        evidence=item.get("evidence") or [],
        warnings=item.get("warnings") or [],
        risks=_risks(result, item.get("warnings") or []),
        recommendations=_recommendations(),
    )


def _result_response(**kwargs: Any) -> LocationAnalysisResponse:
    result = kwargs.pop("result")
    return LocationAnalysisResponse(
        **kwargs,
        opportunity=OpportunitySummary(
            score=result.get("opportunity_score"), conclusion=result.get("conclusion")
        ),
        confidence=ConfidenceSummary(score=result.get("confidence_score")),
        finance=FinanceSummary(
            feasibility=result.get("finance_feasibility"),
            assumptions_provided=bool((result.get("finance_metrics") or {}).get("assumptions")),
            metrics=result.get("finance_metrics") or {},
        ),
        dimension_breakdown=result.get("dimension_scores") or {},
        confidence_breakdown=result.get("confidence") or {},
        risks=_risks(result, kwargs.get("warnings", [])),
        recommendations=_recommendations(),
    )


def _risks(result: dict[str, Any], warnings: list[str]) -> list[str]:
    risks = list(warnings)
    if result.get("confidence_score", 100) < 60:
        risks.append("evidence coverage is insufficient for a definitive decision")
    return risks


def _recommendations() -> list[str]:
    return [
        "Verify pedestrian conditions and operating constraints on site.",
        "Confirm competitor positioning and customer fit with direct observation.",
    ]


def _provider_http_error(error: BaiduMapResponseError) -> HTTPException:
    return _provider_http_error_for_kind(error.kind.value, retryable=error.retryable)


def _provider_http_error_for_kind(kind: str, *, retryable: bool) -> HTTPException:
    code = f"baidu_{kind}_error"
    status_code = (
        status.HTTP_503_SERVICE_UNAVAILABLE
        if kind in {"authentication", "configuration"} or retryable
        else status.HTTP_403_FORBIDDEN
        if kind in {"permission", "ip_restriction", "signature"}
        else status.HTTP_429_TOO_MANY_REQUESTS
        if kind == "quota"
        else status.HTTP_400_BAD_REQUEST
        if kind in {"request", "unknown"}
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return _structured_error(status_code, code, "Baidu provider request failed")


def _raise_for_provider_warnings(warnings: list[str]) -> None:
    for warning in warnings:
        parts = warning.split(":")
        try:
            provider_index = parts.index("baidu_map")
            kind = parts[provider_index + 1]
            disposition = parts[provider_index + 2]
        except (ValueError, IndexError):
            continue
        if kind:
            raise _provider_http_error_for_kind(
                kind, retryable=disposition == "retryable"
            )


def _structured_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})
