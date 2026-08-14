from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.agent_runtime.contracts import CapabilityIntent, CapabilityName
from app.agent_runtime.request_router import (
    CapabilityRoutingError,
    capability_for_intent,
    route_capability,
)
from app.api.location import (
    get_baidu_client_factory,
    get_location_service_factory,
    manual_analysis,
    recommendations,
)
from app.api.operating import analyze_operating
from app.api.pre_open import analyze_pre_open
from app.db.models import Project
from app.db.session import get_db
from app.location.service import LocationAnalysisService
from app.schemas.agent import (
    AgentAnalyzeRequest,
    AgentAnalyzeResponse,
    AgentFailure,
)
from app.schemas.location import (
    LocationRecommendationsRequest,
    ManualLocationAnalysisRequest,
)
from app.schemas.operating import OperatingAnalyzeRequest
from app.schemas.pre_open import PreOpenAnalyzeRequest

router = APIRouter(prefix="/agent", tags=["agent"])
logger = logging.getLogger(__name__)


@router.post("/analyze", response_model=AgentAnalyzeResponse)
def analyze_with_agent(
    request: AgentAnalyzeRequest, db: Session = Depends(get_db)
) -> AgentAnalyzeResponse:
    capability = capability_for_intent(request.intent)
    if request.project_id is None:
        return _clarification(request, capability, ["project_id"])

    project = db.get(Project, request.project_id)
    if project is None:
        return _input_failure(
            request,
            capability,
            code="project_not_found",
            message="project not found",
        )
    try:
        decision = route_capability(intent=request.intent, project_stage=project.stage)
    except CapabilityRoutingError as error:
        return _input_failure(
            request,
            capability,
            code="capability_stage_mismatch",
            message=str(error),
        )

    payload_data = {**request.inputs, "project_id": request.project_id}
    model_type: type[BaseModel]
    if decision.capability == CapabilityName.PRE_OPEN_FEASIBILITY:
        model_type = PreOpenAnalyzeRequest
    elif decision.capability == CapabilityName.OPERATING_DIAGNOSIS:
        model_type = OperatingAnalyzeRequest
    elif request.intent == CapabilityIntent.ANALYZE_LOCATION:
        model_type = ManualLocationAnalysisRequest
    else:
        model_type = LocationRecommendationsRequest

    try:
        payload = model_type.model_validate(payload_data)
    except ValidationError as error:
        missing = _missing_fields(error)
        if missing:
            return _clarification(request, capability, missing)
        return _input_failure(
            request,
            capability,
            code="invalid_capability_input",
            message=_validation_message(error),
        )

    try:
        result = _execute(decision.capability, request, payload, db)
    except HTTPException as error:
        db.rollback()
        return _classified_http_failure(request, capability, error)
    except Exception:
        db.rollback()
        logger.exception("Unified Agent capability execution failed")
        return AgentAnalyzeResponse(
            status="tool_failure",
            capability=capability,
            intent=request.intent,
            failure=AgentFailure(
                category="tool",
                code="capability_execution_failed",
                message="capability execution failed",
                retryable=False,
            ),
        )

    return AgentAnalyzeResponse(
        status="completed",
        capability=capability,
        intent=request.intent,
        result=_serialize(result),
    )


def _execute(
    capability: CapabilityName,
    request: AgentAnalyzeRequest,
    payload: BaseModel,
    db: Session,
) -> object:
    if capability == CapabilityName.PRE_OPEN_FEASIBILITY:
        if not isinstance(payload, PreOpenAnalyzeRequest):
            raise TypeError("invalid pre-open capability payload")
        return analyze_pre_open(payload, db)
    if capability == CapabilityName.OPERATING_DIAGNOSIS:
        if not isinstance(payload, OperatingAnalyzeRequest):
            raise TypeError("invalid operating capability payload")
        return analyze_operating(payload, db)

    if not isinstance(
        payload, (ManualLocationAnalysisRequest, LocationRecommendationsRequest)
    ):
        raise TypeError("invalid location capability payload")

    has_address = bool(getattr(payload, "address", None))
    has_coordinates = (
        getattr(payload, "latitude", None) is not None
        and getattr(payload, "longitude", None) is not None
    )
    mode = LocationAnalysisService.select_capability_mode(
        intent=request.intent,
        has_address=has_address,
        has_coordinates=has_coordinates,
    )
    client_factory = get_baidu_client_factory()
    service_factory = get_location_service_factory()
    if mode == "manual":
        return manual_analysis(
            payload,  # type: ignore[arg-type]
            db,
            client_factory,
            service_factory,
        )
    return recommendations(
        payload,  # type: ignore[arg-type]
        db,
        client_factory,
        service_factory,
    )


def _missing_fields(error: ValidationError) -> list[str]:
    return sorted(
        {
            str(item["loc"][-1])
            for item in error.errors()
            if item["type"] == "missing" and item.get("loc")
        }
    )


def _validation_message(error: ValidationError) -> str:
    first = error.errors()[0]
    field = ".".join(str(part) for part in first.get("loc", ()))
    return f"{field}: {first['msg']}" if field else str(first["msg"])


def _clarification(
    request: AgentAnalyzeRequest,
    capability: CapabilityName,
    missing_fields: list[str],
) -> AgentAnalyzeResponse:
    return AgentAnalyzeResponse(
        status="clarification",
        capability=capability,
        intent=request.intent,
        missing_fields=missing_fields,
    )


def _input_failure(
    request: AgentAnalyzeRequest,
    capability: CapabilityName,
    *,
    code: str,
    message: str,
) -> AgentAnalyzeResponse:
    return AgentAnalyzeResponse(
        status="insufficient_data",
        capability=capability,
        intent=request.intent,
        failure=AgentFailure(category="input", code=code, message=message),
    )


def _classified_http_failure(
    request: AgentAnalyzeRequest,
    capability: CapabilityName,
    error: HTTPException,
) -> AgentAnalyzeResponse:
    detail = error.detail if isinstance(error.detail, dict) else {}
    code = str(detail.get("code", "capability_request_failed"))
    message = str(detail.get("message", error.detail))
    provider_failure = code.startswith("baidu_")
    input_failure = not provider_failure and error.status_code in {400, 404, 422}
    return AgentAnalyzeResponse(
        status=(
            "provider_failure"
            if provider_failure
            else "insufficient_data"
            if input_failure
            else "tool_failure"
        ),
        capability=capability,
        intent=request.intent,
        failure=AgentFailure(
            category=(
                "provider"
                if provider_failure
                else "input"
                if input_failure
                else "tool"
            ),
            code=code,
            message=message,
            retryable=error.status_code in {429, 502, 503, 504},
        ),
    )


def _serialize(value: object) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value
