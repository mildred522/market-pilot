from fastapi.testclient import TestClient

from app.main import app


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
