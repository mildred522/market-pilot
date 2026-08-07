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


def test_from_env_requires_server_api_key(monkeypatch):
    monkeypatch.delenv("BAIDU_MAP_AK", raising=False)

    with pytest.raises(BaiduMapConfigurationError):
        BaiduMapClient.from_env()
