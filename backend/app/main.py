import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

load_dotenv()

from app.api import (
    agent,
    agent_runs,
    analysis,
    corrections,
    dashboard,
    files,
    location,
    operating,
    pre_open,
    projects,
)
from app.db.session import init_db
from app.services.runtime_config import runtime_config
from app.services.runtime_health import knowledge_rag_runtime_health


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="Restaurant Agent API", lifespan=lifespan)


def cors_origins() -> list[str]:
    defaults = ["http://localhost:3000", "http://127.0.0.1:3000"]
    configured = os.getenv("CORS_ORIGINS", "").strip()
    if not configured:
        return defaults
    origins = [
        value.strip().rstrip("/")
        for value in configured.split(",")
        if value.strip().startswith(("http://", "https://"))
    ]
    return list(dict.fromkeys(origins)) or defaults


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(OperationalError)
async def database_operational_error(_, error: OperationalError) -> JSONResponse:
    database_busy = "database is locked" in str(error).lower()
    return JSONResponse(
        status_code=503,
        content={
            "detail": {
                "code": "database_busy" if database_busy else "database_unavailable",
                "message": (
                    "数据正在写入，请稍后重试。"
                    if database_busy
                    else "数据库暂时不可用，请稍后重试。"
                ),
                "retryable": True,
            }
        },
    )


app.include_router(projects.router)
app.include_router(dashboard.router)
app.include_router(pre_open.router)
app.include_router(files.router)
app.include_router(operating.router)
app.include_router(analysis.router)
app.include_router(corrections.router)
app.include_router(agent_runs.router)
app.include_router(location.router)
app.include_router(agent.router)


@app.get("/health")
def health() -> dict[str, object]:
    knowledge = knowledge_rag_runtime_health(
        runtime_config.knowledge_rag_settings()
    )
    return {
        "status": "ok" if knowledge["status"] in {"disabled", "ready"} else "degraded",
        "components": {"knowledge_rag": knowledge},
    }
