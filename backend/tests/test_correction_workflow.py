from fastapi.testclient import TestClient
import pytest

from app.agent_runtime.tool_contracts import ToolExecutionBatch, ToolExecutionResult
from app.corrections import service as correction_service
from app.main import app


def test_confirmed_rent_correction_creates_incremental_analysis_idempotently():
    with TestClient(app) as client:
        project = client.post(
            "/projects", json={"name": "增量重算店", "stage": "operating"}
        ).json()
        source = client.post(
            "/operating/analyze-sample",
            json={"project_id": project["id"], "question": "完整分析"},
        ).json()
        root = client.post(
            f"/analysis/{source['analysis_id']}/chat",
            json={"question": "当前为什么不赚钱？"},
        ).json()
        correction = client.post(
            f"/analysis/{source['analysis_id']}/chat",
            json={
                "parent_version_id": root["answer_version_id"],
                "feedback": "租金不是 18000，应为 25000",
            },
        ).json()
        proposal = correction["correction_proposals"][0]

        first = client.post(
            f"/corrections/{proposal['id']}/confirm",
            json={"idempotency_key": proposal["idempotency_key"]},
        )
        second = client.post(
            f"/corrections/{proposal['id']}/confirm",
            json={"idempotency_key": proposal["idempotency_key"]},
        )
        source_after = client.get(f"/analysis/{source['analysis_id']}").json()
        applied = client.get(f"/analysis/{first.json()['analysis_id']}").json()
        runs = client.get(
            f"/analysis/{first.json()['analysis_id']}/agent-runs"
        ).json()
        run_detail = client.get(
            f"/analysis/{first.json()['analysis_id']}/agent-runs/{runs[0]['request_id']}"
        ).json()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["analysis_id"] == second.json()["analysis_id"]
    assert first.json()["analysis_id"] != source["analysis_id"]
    assert source_after["metrics"]["survival"]["monthly_fixed_cost"] == 50000
    assert applied["metrics"]["survival"]["monthly_fixed_cost"] == 57000
    assert applied["metrics"]["_correction"]["affected_tools"] == [
        "analyze_survival_line"
    ]
    assert applied["metrics"]["_correction"]["metric_changes"]
    assert applied["metrics"]["_agent"]["run_id"] == runs[0]["run_id"]
    assert runs[0]["operation"] == "confirmed_correction"
    assert runs[0]["usage"]["tool_calls"] == 1
    assert run_detail["initial_plan"]["workflow"] is None


def test_confirm_rejects_stale_source_analysis():
    with TestClient(app) as client:
        project = client.post(
            "/projects", json={"name": "冲突保护店", "stage": "operating"}
        ).json()
        source = client.post(
            "/operating/analyze-sample",
            json={"project_id": project["id"], "question": "第一次分析"},
        ).json()
        root = client.post(
            f"/analysis/{source['analysis_id']}/chat",
            json={"question": "当前利润如何？"},
        ).json()
        correction = client.post(
            f"/analysis/{source['analysis_id']}/chat",
            json={
                "parent_version_id": root["answer_version_id"],
                "feedback": "租金改成 25000",
            },
        ).json()
        proposal = correction["correction_proposals"][0]
        client.post(
            "/operating/analyze-sample",
            json={"project_id": project["id"], "question": "更新后的分析"},
        )

        response = client.post(
            f"/corrections/{proposal['id']}/confirm",
            json={"idempotency_key": proposal["idempotency_key"]},
        )
        proposals = client.get(
            f"/analysis/{source['analysis_id']}/corrections"
        ).json()

    assert response.status_code == 409
    assert "stale" in response.json()["detail"]
    assert proposals[0]["status"] == "pending"


def test_correction_without_explicit_value_does_not_create_proposal():
    with TestClient(app) as client:
        project = client.post(
            "/projects", json={"name": "缺值保护店", "stage": "operating"}
        ).json()
        source = client.post(
            "/operating/analyze-sample",
            json={"project_id": project["id"], "question": "完整分析"},
        ).json()
        root = client.post(
            f"/analysis/{source['analysis_id']}/chat",
            json={"question": "当前利润如何？"},
        ).json()
        response = client.post(
            f"/analysis/{source['analysis_id']}/chat",
            json={
                "parent_version_id": root["answer_version_id"],
                "feedback": "租金写错了，请重新算",
            },
        ).json()

    assert response["mode"] == "insufficient_data"
    assert response["correction_proposals"] == []


def test_wrong_idempotency_key_keeps_proposal_pending():
    with TestClient(app) as client:
        source, proposal = _pending_rent_correction(client, "幂等保护店")
        response = client.post(
            f"/corrections/{proposal['id']}/confirm",
            json={"idempotency_key": "00000000-0000-0000-0000-000000000000"},
        )
        proposals = client.get(
            f"/analysis/{source['analysis_id']}/corrections"
        ).json()

    assert response.status_code == 409
    assert proposals[0]["status"] == "pending"


def test_rejected_correction_cannot_be_confirmed():
    with TestClient(app) as client:
        _, proposal = _pending_rent_correction(client, "拒绝保护店")
        rejected = client.post(f"/corrections/{proposal['id']}/reject")
        confirmed = client.post(
            f"/corrections/{proposal['id']}/confirm",
            json={"idempotency_key": proposal["idempotency_key"]},
        )

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert confirmed.status_code == 409


def test_tool_failure_rolls_back_and_allows_safe_retry(
    monkeypatch: pytest.MonkeyPatch,
):
    original_execute = correction_service.execute_operating_tools
    with TestClient(app) as client:
        source, proposal = _pending_rent_correction(client, "回滚保护店")
        monkeypatch.setattr(
            correction_service,
            "execute_operating_tools",
            lambda *_args, **_kwargs: ToolExecutionBatch(
                executions=[
                    ToolExecutionResult(
                        tool_name="analyze_survival_line",
                        output_section="survival",
                        status="failed",
                        error_code="tool_execution_failed",
                        recoverable=True,
                        duration_ms=0,
                    )
                ],
                stopped_early=True,
            ),
        )
        failed = client.post(
            f"/corrections/{proposal['id']}/confirm",
            json={"idempotency_key": proposal["idempotency_key"]},
        )
        after_failure = client.get(
            f"/analysis/{source['analysis_id']}/corrections"
        ).json()[0]
        monkeypatch.setattr(
            correction_service, "execute_operating_tools", original_execute
        )
        retried = client.post(
            f"/corrections/{proposal['id']}/confirm",
            json={"idempotency_key": proposal["idempotency_key"]},
        )

    assert failed.status_code == 422
    assert after_failure["status"] == "pending"
    assert retried.status_code == 200
    assert retried.json()["analysis_id"] != source["analysis_id"]


def _pending_rent_correction(client: TestClient, name: str):
    project = client.post(
        "/projects", json={"name": name, "stage": "operating"}
    ).json()
    source = client.post(
        "/operating/analyze-sample",
        json={"project_id": project["id"], "question": "完整分析"},
    ).json()
    root = client.post(
        f"/analysis/{source['analysis_id']}/chat",
        json={"question": "当前利润如何？"},
    ).json()
    correction = client.post(
        f"/analysis/{source['analysis_id']}/chat",
        json={
            "parent_version_id": root["answer_version_id"],
            "feedback": "租金不是 18000，应为 25000",
        },
    ).json()
    return source, correction["correction_proposals"][0]
