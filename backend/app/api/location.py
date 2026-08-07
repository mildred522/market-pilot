from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import LocationAnalysis, Project
from app.db.session import get_db
from app.external_context.baidu_client import (
    BaiduGeocodeResult,
    BaiduMapClient,
    BaiduMapConfigurationError,
    BaiduMapResponseError,
)
from app.external_context.snapshot_service import ExternalContextSnapshotService
from app.location.collector import PoiCollector
from app.location.evidence import EvidenceVerificationError, LocationEvidenceVerifier
from app.location.feature_builder import LocationFeatureBuilder
from app.location.scorer import LocationScorer
from app.location.service import LocationAnalysisService
from app.schemas.location import (
    Coordinate,
    ConfidenceSummary,
    FinanceSummary,
    LocationAnalysisResponse,
    LocationRecommendationsRequest,
    ManualLocationAnalysisRequest,
    OpportunitySummary,
    RecommendationCandidate,
)

router = APIRouter(prefix="/pre-open/location", tags=["location"])


def get_baidu_client_factory() -> Callable[[], BaiduMapClient]:
    return BaiduMapClient.from_env


def get_location_service_factory() -> Callable[[Session, BaiduMapClient], LocationAnalysisService]:
    def factory(db: Session, baidu_client: BaiduMapClient) -> LocationAnalysisService:
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


@router.post("/manual-analysis", response_model=LocationAnalysisResponse)
def manual_analysis(
    payload: ManualLocationAnalysisRequest,
    db: Session = Depends(get_db),
    client_factory: Callable[[], BaiduMapClient] = Depends(get_baidu_client_factory),
    service_factory: Callable[[Session, BaiduMapClient], LocationAnalysisService] = Depends(
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
            source = "baidu_geocoding"
        else:
            latitude, longitude = payload.latitude, payload.longitude
        analysis = service_factory(db, client).analyze_manual(
            project_id=payload.project_id,
            city=payload.city,
            category=payload.category,
            latitude=latitude,
            longitude=longitude,
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
    client_factory: Callable[[], BaiduMapClient] = Depends(get_baidu_client_factory),
    service_factory: Callable[[Session, BaiduMapClient], LocationAnalysisService] = Depends(
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
    analysis_id: int, db: Session = Depends(get_db)
) -> LocationAnalysisResponse:
    analysis = db.get(LocationAnalysis, analysis_id)
    if analysis is None:
        raise _structured_error(status.HTTP_404_NOT_FOUND, "analysis_not_found", "location analysis not found")
    return _response_for_row(analysis)


def _require_project(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise _structured_error(status.HTTP_404_NOT_FOUND, "project_not_found", "project not found")
    return project


def _coordinate_values(value: BaiduGeocodeResult | dict[str, Any]) -> tuple[float, float]:
    if isinstance(value, dict):
        return float(value["latitude"]), float(value["longitude"])
    return value.latitude, value.longitude


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
        finance=FinanceSummary(feasibility=result.get("finance_feasibility")),
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
        finance=FinanceSummary(feasibility=result.get("finance_feasibility")),
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
    kind = error.kind.value
    code = f"baidu_{kind}_error"
    status_code = (
        status.HTTP_403_FORBIDDEN
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
        if len(parts) >= 3 and parts[0] == "baidu_map":
            kind = parts[1]
            retryable = parts[2] == "retryable"
            status_code = (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if retryable
                else status.HTTP_403_FORBIDDEN
                if kind in {"permission", "ip_restriction", "signature"}
                else status.HTTP_429_TOO_MANY_REQUESTS
                if kind == "quota"
                else status.HTTP_400_BAD_REQUEST
            )
            raise _structured_error(
                status_code,
                f"baidu_{kind}_error",
                "Baidu provider request failed",
            )


def _structured_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})
