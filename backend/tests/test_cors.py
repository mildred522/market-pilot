import sqlite3

from sqlalchemy.exc import OperationalError
from fastapi.testclient import TestClient

from app.db.session import get_db
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
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3027",
    ]


def test_database_lock_returns_retryable_cors_response():
    class LockedSession:
        def add(self, _):
            pass

        def commit(self):
            raise OperationalError(
                "INSERT INTO projects",
                {},
                sqlite3.OperationalError("database is locked"),
            )

    def locked_db():
        yield LockedSession()

    app.dependency_overrides[get_db] = locked_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/projects",
                json={"name": "locked", "stage": "pre_open"},
                headers={"Origin": "http://localhost:3000"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.json()["detail"] == {
        "code": "database_busy",
        "message": "数据正在写入，请稍后重试。",
        "retryable": True,
    }
