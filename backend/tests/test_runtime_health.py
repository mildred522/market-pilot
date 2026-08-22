import httpx

from app.knowledge.contracts import KnowledgeRagSettings
from app.services.runtime_health import knowledge_rag_runtime_health


def test_knowledge_rag_runtime_health_checks_configured_collection():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/collections/knowledge-v1"
        assert request.headers["api-key"] == "secret"
        return httpx.Response(200, json={"status": "ok", "result": {}})

    result = knowledge_rag_runtime_health(
        KnowledgeRagSettings(
            enabled=True,
            qdrant_url="https://qdrant.example.test",
            qdrant_api_key="secret",
            collection="knowledge-v1",
        ),
        transport=httpx.MockTransport(handler),
    )

    assert result["status"] == "ready"
    assert result["error_code"] is None


def test_knowledge_rag_runtime_health_degrades_without_qdrant():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    result = knowledge_rag_runtime_health(
        KnowledgeRagSettings(enabled=True),
        transport=httpx.MockTransport(handler),
    )

    assert result["status"] == "degraded"
    assert result["error_code"] == "qdrant_unreachable"


def test_knowledge_rag_runtime_health_is_disabled_without_network_call():
    result = knowledge_rag_runtime_health(KnowledgeRagSettings())

    assert result == {
        "status": "disabled",
        "enabled": False,
        "collection": "market_pilot_knowledge_v1",
        "latency_ms": 0,
        "error_code": None,
    }
