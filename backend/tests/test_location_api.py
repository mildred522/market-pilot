from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, LocationAnalysis, Project
from app.db.session import get_db
from app.external_context.baidu_client import (
    BaiduMapConfigurationError,
    BaiduMapErrorKind,
    BaiduMapResponseError,
)
from app.location.evidence import EvidenceVerificationError
from app.main import app
from app.api import location as location_api


class FakeClient:
    def __init__(self, *, geocode=None, error=None):
        self.geocode_result = geocode
        self.error = error
        self.calls = []

    def geocode(self, *, address, city):
        self.calls.append((address, city))
        if self.error:
            raise self.error
        return self.geocode_result


class FakeService:
    def __init__(self, row=None, *, error=None):
        self.row = row
        self.error = error
        self.manual_calls = []
        self.recommendation_calls = []

    def analyze_manual(self, **kwargs):
        self.manual_calls.append(kwargs)
        if self.error:
            raise self.error
        return self.row

    def analyze_recommendations(self, **kwargs):
        self.recommendation_calls.append(kwargs)
        if self.error:
            raise self.error
        return self.row

    def get_analysis(self, analysis_id):
        return self.row if self.row and self.row.id == analysis_id else None


def make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    project = Project(name="API project", stage="pre_open")
    session.add(project)
    session.commit()
    return session, project.id


def make_row(session, project_id, *, mode="manual", result=None, status="completed"):
    row = LocationAnalysis(
        mode=mode,
        project_id=project_id,
        input_scope_json={"city": "Chengdu", "district": "High-tech Zone"},
        center_latitude=30.57 if mode == "manual" else None,
        center_longitude=104.06 if mode == "manual" else None,
        status=status,
        result_json=result or {},
        evidence_json=[],
        warnings_json=[],
    )
    session.add(row)
    session.commit()
    return row


@pytest.fixture
def api_setup(monkeypatch):
    session, project_id = make_db()
    client = FakeClient(geocode={"latitude": 30.5728, "longitude": 104.0668})
    service = FakeService()
    app.dependency_overrides[get_db] = lambda: (yield session)
    app.dependency_overrides[location_api.get_baidu_client_factory] = lambda: lambda: client
    app.dependency_overrides[location_api.get_location_service_factory] = (
        lambda: lambda db, baidu_client: service
    )
    yield session, project_id, client, service
    app.dependency_overrides.clear()
    session.close()


def payload(project_id, **overrides):
    body = {
        "project_id": project_id,
        "city": "Chengdu",
        "district": "High-tech Zone",
        "category": "milk-tea",
        "target_customer": "office workers",
        "planned_average_order_value": 22,
        "address": "No. 1 Tianfu Avenue",
        "coordinate_system": "bd09ll",
    }
    body.update(overrides)
    return body


def test_manual_coordinate_request_calls_service_without_geocoding(api_setup):
    session, project_id, client, service = api_setup
    service.row = make_row(session, project_id)

    with TestClient(app) as http:
        response = http.post(
            "/pre-open/location/manual-analysis",
            json=payload(project_id, address=None, latitude=30.5728, longitude=104.0668),
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "manual"
    assert client.calls == []
    assert service.manual_calls[0]["latitude"] == 30.5728


def test_manual_address_request_geocodes_and_returns_source(api_setup):
    session, project_id, client, service = api_setup
    service.row = make_row(session, project_id)

    with TestClient(app) as http:
        response = http.post(
            "/pre-open/location/manual-analysis", json=payload(project_id)
        )

    assert response.status_code == 200
    assert client.calls == [("No. 1 Tianfu Avenue", "Chengdu")]
    assert response.json()["center"]["source"] == "baidu_geocoding"


@pytest.mark.parametrize(
    "location_fields",
    [{}, {"latitude": 30.5}, {"address": "x", "latitude": 30.5, "longitude": 104.0}],
)
def test_manual_requires_exactly_one_complete_location(location_fields, api_setup):
    _, project_id, _, _ = api_setup
    body = payload(project_id, address=None, latitude=None, longitude=None)
    body.update(location_fields)
    with TestClient(app) as http:
        response = http.post("/pre-open/location/manual-analysis", json=body)
    assert response.status_code == 422


def test_recommendations_default_candidate_count_and_bounded_radius(api_setup):
    session, project_id, _, service = api_setup
    service.row = make_row(session, project_id, mode="recommendations")
    with TestClient(app) as http:
        response = http.post(
            "/pre-open/location/recommendations",
            json=payload(project_id, address=None, radius_meters=1500),
        )
    assert response.status_code == 200
    assert service.recommendation_calls[0]["max_candidates"] == 5


@pytest.mark.parametrize("field", ["candidate_count", "radius_meters"])
def test_recommendations_reject_invalid_bounds(field, api_setup):
    _, project_id, _, _ = api_setup
    value = 2 if field == "candidate_count" else 0
    with TestClient(app) as http:
        response = http.post(
            "/pre-open/location/recommendations",
            json=payload(project_id, address=None, **{field: value}),
        )
    assert response.status_code == 422


def test_missing_project_is_checked_before_baidu_factory(api_setup):
    _, _, client, service = api_setup
    with TestClient(app) as http:
        response = http.post(
            "/pre-open/location/manual-analysis",
            json=payload(999, address=None, latitude=30.5, longitude=104.0),
        )
    assert response.status_code == 404
    assert client.calls == []
    assert service.manual_calls == []


def test_missing_ak_is_structured_503(monkeypatch):
    session, project_id = make_db()
    app.dependency_overrides[get_db] = lambda: (yield session)
    app.dependency_overrides[location_api.get_baidu_client_factory] = (
        lambda: lambda: (_ for _ in ()).throw(BaiduMapConfigurationError("missing"))
    )
    try:
        with TestClient(app) as http:
            response = http.post(
                "/pre-open/location/manual-analysis",
                json=payload(project_id, address=None, latitude=30.5, longitude=104.0),
            )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "baidu_configuration_error"
    finally:
        app.dependency_overrides.clear()
        session.close()


@pytest.mark.parametrize(
    ("kind", "expected"),
    [(BaiduMapErrorKind.PERMISSION, 403), (BaiduMapErrorKind.QUOTA, 429),
     (BaiduMapErrorKind.RETRYABLE, 503)],
)
def test_provider_errors_are_classified(kind, expected, api_setup):
    session, project_id, _, service = api_setup
    service.row = None
    service.error = BaiduMapResponseError("provider", kind=kind, retryable=kind == BaiduMapErrorKind.RETRYABLE)
    with TestClient(app) as http:
        response = http.post(
            "/pre-open/location/manual-analysis",
            json=payload(project_id, address=None, latitude=30.5, longitude=104.0),
        )
    assert response.status_code == expected
    assert response.json()["detail"]["code"].startswith("baidu_")


def test_retrieval_returns_persisted_normalized_result(api_setup):
    session, project_id, _, service = api_setup
    service.row = make_row(
        session,
        project_id,
        result={"opportunity_score": 72, "confidence_score": 81},
    )
    with TestClient(app) as http:
        response = http.get(f"/pre-open/location/analyses/{service.row.id}")
    assert response.status_code == 200
    assert response.json()["opportunity"]["score"] == 72


def test_retrieval_missing_analysis_is_404(api_setup):
    with TestClient(app) as http:
        response = http.get("/pre-open/location/analyses/999")
    assert response.status_code == 404


def test_evidence_verification_failure_is_structured_500(api_setup):
    session, project_id, _, service = api_setup
    service.error = EvidenceVerificationError("missing conclusion")
    with TestClient(app) as http:
        response = http.post(
            "/pre-open/location/manual-analysis",
            json=payload(project_id, address=None, latitude=30.5, longitude=104.0),
        )
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "evidence_verification_failed"
