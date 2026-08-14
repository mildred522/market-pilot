from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.agent_runtime.contracts import CapabilityIntent
from app.api import agent as agent_api
from app.main import app


def create_project(client: TestClient, *, stage: str) -> int:
    response = client.post(
        "/projects", json={"name": f"Agent {stage}", "stage": stage}
    )
    assert response.status_code == 201
    return response.json()["id"]


def pre_open_inputs() -> dict[str, object]:
    return {
        "category": "粉面",
        "city": "成都",
        "location_type": "community",
        "area_sqm": 60,
        "seats": 28,
        "monthly_rent": 18000,
        "total_investment": 280000,
        "own_capital": 150000,
        "debt_amount": 130000,
        "expected_daily_orders": 90,
        "expected_avg_order_value": 24,
        "expected_gross_margin": 0.62,
        "is_franchise": True,
        "franchise_fee": 68000,
        "competitor_count": 8,
        "storefront_visibility": "medium",
    }


def test_unified_agent_completes_pre_open_feasibility():
    with TestClient(app) as client:
        project_id = create_project(client, stage="pre_open")
        response = client.post(
            "/agent/analyze",
            json={
                "project_id": project_id,
                "intent": CapabilityIntent.ASSESS_FEASIBILITY,
                "inputs": pre_open_inputs(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["capability"] == "pre_open_feasibility"
    assert body["result"]["metrics"]["estimated_daily_revenue"] == 2160


def test_unified_agent_returns_exact_missing_fields_as_clarification():
    with TestClient(app) as client:
        project_id = create_project(client, stage="pre_open")
        response = client.post(
            "/agent/analyze",
            json={
                "project_id": project_id,
                "intent": "assess_feasibility",
                "inputs": {"category": "茶饮", "city": "成都"},
            },
        )

    body = response.json()
    assert body["status"] == "clarification"
    assert "monthly_rent" in body["missing_fields"]
    assert "expected_daily_orders" in body["missing_fields"]
    assert body["result"] is None


def test_unified_agent_does_not_allow_inputs_to_override_project_id():
    with TestClient(app) as client:
        project_id = create_project(client, stage="pre_open")
        inputs = pre_open_inputs()
        inputs["project_id"] = project_id + 999
        response = client.post(
            "/agent/analyze",
            json={
                "project_id": project_id,
                "intent": "assess_feasibility",
                "inputs": inputs,
            },
        )

    body = response.json()
    assert body["status"] == "completed"
    assert body["result"]["project_id"] == project_id


def test_unified_agent_rejects_intent_that_conflicts_with_project_stage():
    with TestClient(app) as client:
        project_id = create_project(client, stage="pre_open")
        response = client.post(
            "/agent/analyze",
            json={
                "project_id": project_id,
                "intent": "diagnose_operations",
                "inputs": {},
            },
        )

    body = response.json()
    assert body["status"] == "insufficient_data"
    assert body["failure"]["code"] == "capability_stage_mismatch"


def test_unified_agent_dispatches_validated_manual_location(monkeypatch):
    observed = {}

    def fake_manual(payload, db, client_factory, service_factory):
        observed["payload"] = payload
        return {"mode": "manual", "analysis_id": 42}

    monkeypatch.setattr(agent_api, "manual_analysis", fake_manual)
    with TestClient(app) as client:
        project_id = create_project(client, stage="pre_open")
        response = client.post(
            "/agent/analyze",
            json={
                "project_id": project_id,
                "intent": "analyze_location",
                "inputs": {
                    "city": "成都",
                    "district": "高新区",
                    "category": "茶饮",
                    "target_customer": "写字楼客群",
                    "planned_average_order_value": 22.0,
                    "address": "天府三街 1 号",
                },
            },
        )

    body = response.json()
    assert body["status"] == "completed"
    assert body["capability"] == "location_analysis"
    assert body["result"]["mode"] == "manual"
    assert observed["payload"].address == "天府三街 1 号"


def test_unified_location_rejects_low_level_provider_controls():
    with TestClient(app) as client:
        project_id = create_project(client, stage="pre_open")
        response = client.post(
            "/agent/analyze",
            json={
                "project_id": project_id,
                "intent": "recommend_locations",
                "inputs": {
                    "city": "成都",
                    "district": "高新区",
                    "category": "茶饮",
                    "target_customer": "写字楼客群",
                    "planned_average_order_value": 22.0,
                    "keywords": ["奶茶", "咖啡"],
                },
            },
        )

    body = response.json()
    assert body["status"] == "insufficient_data"
    assert body["failure"]["code"] == "invalid_capability_input"


def test_unified_agent_dispatches_operating_diagnosis(monkeypatch):
    observed = {}

    def fake_operating(payload, db):
        observed["payload"] = payload
        return {"analysis_id": 7, "summary": "营业诊断完成"}

    monkeypatch.setattr(agent_api, "analyze_operating", fake_operating)
    with TestClient(app) as client:
        project_id = create_project(client, stage="operating")
        response = client.post(
            "/agent/analyze",
            json={
                "project_id": project_id,
                "intent": "diagnose_operations",
                "inputs": {
                    "question": "最近利润为什么下降？",
                    "analysis_mode": "focused",
                    "orders": {"file_id": 1, "mapping": {}},
                    "menu_items": {"file_id": 2, "mapping": {}},
                    "reviews": {"file_id": 3, "mapping": {}},
                    "cost_assumptions": {
                        "monthly_rent": 18000.0,
                        "monthly_labor": 24000.0,
                        "monthly_utilities": 3000.0,
                    },
                },
            },
        )

    body = response.json()
    assert body["status"] == "completed"
    assert body["capability"] == "operating_diagnosis"
    assert observed["payload"].analysis_mode == "focused"


def test_unified_agent_classifies_provider_failure(monkeypatch):
    def fail_manual(*args, **kwargs):
        raise HTTPException(
            status_code=503,
            detail={"code": "baidu_quota_error", "message": "quota exhausted"},
        )

    monkeypatch.setattr(agent_api, "manual_analysis", fail_manual)
    with TestClient(app) as client:
        project_id = create_project(client, stage="pre_open")
        response = client.post(
            "/agent/analyze",
            json={
                "project_id": project_id,
                "intent": "analyze_location",
                "inputs": {
                    "city": "成都",
                    "district": "高新区",
                    "category": "茶饮",
                    "target_customer": "写字楼客群",
                    "planned_average_order_value": 22.0,
                    "address": "天府三街 1 号",
                },
            },
        )

    body = response.json()
    assert body["status"] == "provider_failure"
    assert body["failure"] == {
        "category": "provider",
        "code": "baidu_quota_error",
        "message": "quota exhausted",
        "retryable": True,
    }


def test_unified_agent_classifies_domain_input_failure(monkeypatch):
    def fail_operating(*args, **kwargs):
        raise HTTPException(
            status_code=422,
            detail={"code": "missing_menu_items", "message": "missing costs"},
        )

    monkeypatch.setattr(agent_api, "analyze_operating", fail_operating)
    with TestClient(app) as client:
        project_id = create_project(client, stage="operating")
        response = client.post(
            "/agent/analyze",
            json={
                "project_id": project_id,
                "intent": "diagnose_operations",
                "inputs": {
                    "question": "利润为什么下降？",
                    "orders": {"file_id": 1, "mapping": {}},
                    "menu_items": {"file_id": 2, "mapping": {}},
                    "reviews": {"file_id": 3, "mapping": {}},
                    "cost_assumptions": {
                        "monthly_rent": 18000.0,
                        "monthly_labor": 24000.0,
                        "monthly_utilities": 3000.0,
                    },
                },
            },
        )

    body = response.json()
    assert body["status"] == "insufficient_data"
    assert body["failure"]["category"] == "input"
    assert body["failure"]["code"] == "missing_menu_items"
