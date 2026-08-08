from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import dashboard
from app.agent_runtime.llm_client import OpenAiCompatibleLlmClient, llm_client_from_environment
from app.external_context.baidu_client import BaiduMapErrorKind, BaiduMapResponseError
from app.db.models import AnalysisResult, Base, LocationAnalysis, Project, UploadedFile
from app.db.session import get_db
from app.main import app
from app.services.runtime_config import runtime_config


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    for name in (
        "BAIDU_MAP_AK",
        "AGENT_LLM_API_KEY",
        "AGENT_LLM_MODEL",
        "AGENT_LLM_BASE_URL",
        "AGENT_LLM_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)
    runtime_config.clear("baidu")
    runtime_config.clear("agent")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine)

    def override_db() -> Generator[Session]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    runtime_config.clear("baidu")
    runtime_config.clear("agent")
    engine.dispose()


def test_overview_returns_real_counts_and_recent_reports(client: TestClient) -> None:
    pre_open = client.post("/projects", json={"name": "泉州候选店", "stage": "pre_open"}).json()
    operating = client.post("/projects", json={"name": "厦门经营店", "stage": "operating"}).json()

    with next(app.dependency_overrides[get_db]()) as db:
        db.add(
            AnalysisResult(
                project_id=operating["id"], stage="operating", summary="午市收入承压",
                metrics_json={}, evidence_json=[], actions_json=[], warnings_json=[]
            )
        )
        db.add(UploadedFile(project_id=operating["id"], file_type="orders", original_name="orders.csv", storage_path="ignored.csv"))
        db.add(LocationAnalysis(mode="recommendations", project_id=pre_open["id"], input_scope_json={}, status="completed", result_json={}, evidence_json=[], warnings_json=[]))
        db.commit()

    body = client.get("/dashboard/overview").json()
    assert body["counts"] == {
        "projects": 2, "pre_open_projects": 1, "operating_projects": 1,
        "analyses": 1, "uploaded_files": 1, "location_analyses": 1,
    }
    assert body["recent_analyses"][0]["project_name"] == "厦门经营店"
    assert body["recent_analyses"][0]["summary"] == "午市收入承压"


def test_runtime_integrations_never_echo_credentials(client: TestClient) -> None:
    baidu_secret = "baidu-test-secret-123"
    baidu = client.put("/dashboard/integrations/baidu", json={"api_key": baidu_secret})
    assert baidu.status_code == 200
    assert baidu.json() == {"configured": True, "source": "runtime"}
    assert baidu_secret not in baidu.text

    agent_secret = "agent-test-secret-456"
    agent = client.put(
        "/dashboard/integrations/agent",
        json={"api_key": agent_secret, "model": "test-model", "base_url": "https://llm.example/v1", "provider": "test-provider"},
    )
    assert agent.status_code == 200
    assert agent_secret not in agent.text
    configured_client = llm_client_from_environment()
    assert isinstance(configured_client, OpenAiCompatibleLlmClient)
    assert configured_client.model == "test-model"
    assert configured_client.provider == "test-provider"

    cleared = client.delete("/dashboard/integrations/agent")
    assert cleared.status_code == 200
    assert cleared.json()["configured"] is False


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/dashboard/integrations/baidu", {"api_key": "short"}),
        ("/dashboard/integrations/agent", {"api_key": "long-enough", "model": "test", "base_url": "ftp://invalid", "provider": "test"}),
    ],
)
def test_invalid_integration_config_is_rejected(client: TestClient, path: str, payload: dict[str, str]) -> None:
    assert client.put(path, json=payload).status_code == 422


def test_unconfigured_agent_probe_returns_readable_result(client: TestClient) -> None:
    response = client.post("/dashboard/integrations/agent/test")

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["code"] == "agent_request_failed"
    assert "尚未配置" in response.json()["message"]


def test_successful_probe_returns_latency_and_safe_details(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        dashboard,
        "_probe_baidu",
        lambda: {"provider": "baidu-place", "sample_total": 12},
    )

    response = client.post("/dashboard/integrations/baidu/test")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["latency_ms"] >= 0
    assert response.json()["details"]["sample_total"] == 12
    assert "api_key" not in response.text.lower()


def test_baidu_probe_translates_ip_restriction(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_probe() -> None:
        raise BaiduMapResponseError(
            "provider detail",
            provider_status=210,
            kind=BaiduMapErrorKind.IP_RESTRICTION,
        )

    monkeypatch.setattr(dashboard, "_probe_baidu", fail_probe)
    body = client.post("/dashboard/integrations/baidu/test").json()

    assert body["ok"] is False
    assert body["code"] == "baidu_ip_restriction"
    assert body["message"] == "当前服务器出口 IP 不在百度白名单中"
