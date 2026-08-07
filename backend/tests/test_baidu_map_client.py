import json
from pathlib import Path

import httpx
import pytest

from app.external_context.baidu_client import (
    BaiduMapClient,
    BaiduMapConfigurationError,
    BaiduMapResponseError,
)

FIXTURE = Path(__file__).parent / "fixtures/external/baidu_context_sample.json"


def test_search_nearby_sends_strict_circle_params_and_normalizes_pois():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        result = BaiduMapClient(
            "test-ak", http_client=http_client
        ).search_nearby(
            query="奶茶",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=800,
        )

    assert captured_request is not None
    assert captured_request.url.params["radius_limit"] == "true"
    assert captured_request.url.params["scope"] == "2"
    assert captured_request.url.params["page_size"] == "20"
    assert captured_request.url.params["coord_type"] == "3"
    assert result.total == 4
    assert result.pois[0].rating == 4.6
    assert result.pois[0].comment_count == 320
    assert result.pois[0].distance_meters == 120


def test_search_nearby_raises_provider_status_error():
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={"status": 4, "message": "quota"},
        )
    )

    with httpx.Client(transport=transport) as http_client:
        with pytest.raises(BaiduMapResponseError, match="status=4"):
            BaiduMapClient(
                "test-ak", http_client=http_client
            ).search_nearby(
                query="奶茶",
                latitude=30.5728,
                longitude=104.0668,
                radius_meters=800,
            )


def test_search_nearby_page_sends_requested_page_and_options():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"status": 0, "total": 0, "results": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        result = BaiduMapClient("test-ak", http_client=http_client).search_nearby_page(
            query="果茶",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=500,
            page_num=1,
            page_size=10,
            radius_limit=False,
            scope=1,
            coord_type=1,
            filter="industry_type:life",
        )

    assert captured_request is not None
    params = captured_request.url.params
    assert params["query"] == "果茶"
    assert params["page_num"] == "1"
    assert params["page_size"] == "10"
    assert params["radius_limit"] == "false"
    assert params["scope"] == "1"
    assert params["coord_type"] == "1"
    assert params["filter"] == "industry_type:life"
    assert result.page_num == 1
    assert result.page_size == 10


def test_search_region_page_uses_region_search_parameters():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"status": 0, "total": 0, "results": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        result = BaiduMapClient("test-ak", http_client=http_client).search_region_page(
            query="奶茶",
            region="成都市",
            page_num=1,
            page_size=20,
            scope=2,
            coord_type=3,
            filter="industry_type:cater",
        )

    assert captured_request is not None
    params = captured_request.url.params
    assert captured_request.url.path == "/place/v2/search"
    assert params["region"] == "成都市"
    assert "location" not in params
    assert "radius" not in params
    assert params["page_num"] == "1"
    assert result.region == "成都市"
    assert result.center_latitude is None
    assert result.radius_meters is None


@pytest.mark.parametrize("page_size", [0, 21])
def test_search_page_rejects_page_size_outside_provider_limit(page_size: int):
    with pytest.raises(ValueError, match="page_size"):
        BaiduMapClient("test-ak").search_nearby_page(
            query="奶茶",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=800,
            page_size=page_size,
        )


def test_search_region_page_normalizes_provider_status_error():
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"status": 4, "message": "quota"})
    )

    with httpx.Client(transport=transport) as http_client:
        with pytest.raises(BaiduMapResponseError, match="status=4"):
            BaiduMapClient("test-ak", http_client=http_client).search_region_page(
                query="奶茶",
                region="成都市",
            )


def test_search_page_normalizes_transport_error_without_exposing_api_key():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(BaiduMapResponseError) as exc_info:
            BaiduMapClient(
                "secret-test-ak", http_client=http_client
            ).search_nearby_page(
                query="奶茶",
                latitude=30.5728,
                longitude=104.0668,
                radius_meters=800,
            )

    assert "secret-test-ak" not in str(exc_info.value)


def test_from_env_requires_server_api_key(monkeypatch):
    monkeypatch.delenv("BAIDU_MAP_AK", raising=False)

    with pytest.raises(BaiduMapConfigurationError):
        BaiduMapClient.from_env()
