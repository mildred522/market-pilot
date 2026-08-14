from fastapi.testclient import TestClient

from app.main import app, cors_origins


def test_cors_allows_frontend_preflight_request():
    with TestClient(app) as client:
        response = client.options(
            "/projects",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_origins_accepts_explicit_local_test_origin(monkeypatch):
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3027",
    )

    assert cors_origins() == [
        "http://localhost:3000",
        "http://127.0.0.1:3027",
    ]
