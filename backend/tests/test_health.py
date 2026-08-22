import importlib

from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_component_status(monkeypatch):
    main_module = importlib.import_module("app.main")
    monkeypatch.setattr(
        main_module,
        "knowledge_rag_runtime_health",
        lambda _settings: {
            "status": "disabled",
            "enabled": False,
            "collection": "market_pilot_knowledge_v1",
            "latency_ms": 0,
            "error_code": None,
        },
    )
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "components": {
            "knowledge_rag": {
                "status": "disabled",
                "enabled": False,
                "collection": "market_pilot_knowledge_v1",
                "latency_ms": 0,
                "error_code": None,
            }
        },
    }
