from __future__ import annotations

from time import perf_counter
from urllib.parse import quote

import httpx

from app.knowledge.contracts import KnowledgeRagSettings


def knowledge_rag_runtime_health(
    settings: KnowledgeRagSettings,
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, object]:
    if not settings.enabled:
        return {
            "status": "disabled",
            "enabled": False,
            "collection": settings.collection,
            "latency_ms": 0,
            "error_code": None,
        }

    started = perf_counter()
    headers = (
        {"api-key": settings.qdrant_api_key}
        if settings.qdrant_api_key
        else {}
    )
    url = (
        f"{settings.qdrant_url.rstrip('/')}/collections/"
        f"{quote(settings.collection, safe='')}"
    )
    try:
        with httpx.Client(
            timeout=min(settings.retrieval_timeout_seconds, 1.5),
            transport=transport,
        ) as client:
            response = client.get(url, headers=headers)
        ready = response.is_success
        error_code = None if ready else "qdrant_collection_unavailable"
    except (httpx.HTTPError, OSError):
        ready = False
        error_code = "qdrant_unreachable"
    return {
        "status": "ready" if ready else "degraded",
        "enabled": True,
        "collection": settings.collection,
        "latency_ms": max(0, round((perf_counter() - started) * 1000)),
        "error_code": error_code,
    }
