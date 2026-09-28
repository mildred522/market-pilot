from time import perf_counter

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser, auth_is_disabled, get_current_user, require_admin
from app.db.models import (
    AnalysisResult,
    LocationAnalysis,
    Project,
    UploadedFile,
)
from app.db.session import get_db
from app.agent_runtime.llm_client import LlmError, llm_client_from_environment
from app.external_context.baidu_client import (
    BaiduMapConfigurationError,
    BaiduMapResponseError,
)
from app.external_context.factory import get_location_provider_factory
from app.schemas.dashboard import (
    AgentIntegrationUpdate,
    BaiduIntegrationUpdate,
    IntegrationName,
)
from app.services.runtime_config import runtime_config

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview")
def overview(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    stage_query = select(Project.stage, func.count(Project.id)).group_by(Project.stage)
    recent_query = (
        select(AnalysisResult, Project.name)
        .join(Project, Project.id == AnalysisResult.project_id)
        .order_by(AnalysisResult.id.desc())
        .limit(5)
    )
    if not auth_is_disabled():
        stage_query = stage_query.where(Project.owner_user_id == current_user.id)
        recent_query = recent_query.where(Project.owner_user_id == current_user.id)
    stage_counts = dict(db.execute(stage_query).all())
    recent_rows = db.execute(recent_query).all()
    return {
        "workspace": {
            "name": current_user.email,
            "role": "管理员" if current_user.is_admin else "成员",
            "account_mode": "authenticated",
        },
        "counts": {
            "projects": _count_projects(db, current_user),
            "pre_open_projects": int(stage_counts.get("pre_open", 0)),
            "operating_projects": int(stage_counts.get("operating", 0)),
            "analyses": _count_for_projects(db, AnalysisResult, current_user),
            "uploaded_files": _count_for_projects(db, UploadedFile, current_user),
            "location_analyses": _count_for_projects(db, LocationAnalysis, current_user),
        },
        "integrations": runtime_config.status(),
        "recent_analyses": [
            {
                "id": analysis.id,
                "project_id": analysis.project_id,
                "project_name": project_name,
                "stage": analysis.stage,
                "summary": analysis.summary,
            }
            for analysis, project_name in recent_rows
        ],
    }


@router.put("/integrations/baidu")
def update_baidu(
    payload: BaiduIntegrationUpdate,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    require_admin(current_user)
    runtime_config.set_baidu_key(payload.api_key)
    return runtime_config.status()["baidu"]


@router.put("/integrations/agent")
def update_agent(
    payload: AgentIntegrationUpdate,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    require_admin(current_user)
    runtime_config.set_agent(
        api_key=payload.api_key,
        model=payload.model,
        base_url=payload.base_url,
        provider=payload.provider,
        planner_model=payload.planner_model,
        synthesizer_model=payload.synthesizer_model,
        followup_model=payload.followup_model,
    )
    return runtime_config.status()["agent"]


@router.delete("/integrations/{integration}")
def clear_integration(
    integration: IntegrationName,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    require_admin(current_user)
    runtime_config.clear(integration)
    return runtime_config.status()[integration]


class _AgentProbeResponse(BaseModel):
    ok: bool


@router.post("/integrations/{integration}/test")
def test_integration(
    integration: IntegrationName,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    require_admin(current_user)
    started_at = perf_counter()
    try:
        details = (
            _probe_baidu()
            if integration == "baidu"
            else _probe_agent()
        )
        return {
            "ok": True,
            "latency_ms": round((perf_counter() - started_at) * 1000),
            "message": "真实请求响应正常",
            "details": details,
        }
    except BaiduMapConfigurationError:
        return _failed_probe(started_at, "尚未配置百度地图 AK", "not_configured")
    except BaiduMapResponseError as error:
        return _failed_probe(
            started_at,
            _baidu_error_message(error),
            f"baidu_{error.kind.value}",
        )
    except LlmError as error:
        return _failed_probe(started_at, str(error), "agent_request_failed")
    except Exception:
        return _failed_probe(started_at, "连接测试发生未知错误", "unknown_error")


def _probe_baidu() -> dict[str, object]:
    result = get_location_provider_factory()().search_nearby_page(
        query="餐厅",
        latitude=24.8741,
        longitude=118.6757,
        radius_meters=500,
        page_size=1,
        scope=1,
        filter=None,
    )
    provider = runtime_config.baidu_provider()
    return {"provider": provider, "sample_total": result.total}


def _probe_agent() -> dict[str, object]:
    client = llm_client_from_environment()
    if not client.configured:
        raise LlmError("尚未配置 Agent API Key 和模型")
    client.generate_json(
        system_prompt="You are a connection probe. Return only the requested JSON.",
        user_prompt='Return {"ok": true}.',
        response_model=_AgentProbeResponse,
        temperature=0,
    )
    return {"provider": client.provider, "model": client.model}


def _failed_probe(started_at: float, message: str, code: str) -> dict[str, object]:
    return {
        "ok": False,
        "latency_ms": round((perf_counter() - started_at) * 1000),
        "message": message,
        "code": code,
        "details": {},
    }


def _baidu_error_message(error: BaiduMapResponseError) -> str:
    messages = {
        "authentication": "百度 AK 鉴权失败",
        "ip_restriction": "当前服务器出口 IP 不在百度白名单中",
        "signature": "百度 SN 签名校验失败",
        "permission": "百度 AK 未开通地点检索服务",
        "quota": "百度地图调用额度或并发已达到限制",
        "rate_limit": "百度地图请求过快，请稍后重试",
        "retryable": "百度地图暂时不可用或请求超时",
    }
    return messages.get(error.kind.value, "百度地图请求失败")


def _count_projects(db: Session, current_user: CurrentUser) -> int:
    query = select(func.count()).select_from(Project)
    if not auth_is_disabled():
        query = query.where(Project.owner_user_id == current_user.id)
    return int(db.scalar(query) or 0)


def _count_for_projects(
    db: Session, model: type[object], current_user: CurrentUser
) -> int:
    query = (
        select(func.count())
        .select_from(model)
        .join(Project, Project.id == model.project_id)  # type: ignore[attr-defined]
    )
    if not auth_is_disabled():
        query = query.where(Project.owner_user_id == current_user.id)
    return int(db.scalar(query) or 0)
