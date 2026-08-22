import json

import httpx
import pytest

from app.external_context.baidu_mcp_provider import BaiduMcpProvider
from app.external_context.baidu_client import BaiduMapResponseError


MCP_RESULT = {
    "status": 0,
    "message": "ok",
    "total": 1,
    "results": [
        {
            "uid": "poi-1",
            "name": "测试奶茶店",
            "location": {"lat": 30.57, "lng": 104.06},
            "address": "测试路 1 号",
            "status": "",
            "detail_info": {
                "classified_poi_tag": "美食;饮品店;奶茶店",
                "distance": 120,
                "brand": "测试品牌",
                "price": "18",
                "overall_rating": "4.6",
                "comment_num": "42",
            },
        }
    ],
}


def response_for(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    method = body["method"]
    if method == "initialize":
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
    if method == "notifications/initialized":
        return httpx.Response(202)
    if method == "tools/call":
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(MCP_RESULT)}
                    ],
                    "isError": False,
                },
            },
        )
    raise AssertionError(method)


def test_mcp_provider_initializes_and_normalizes_search_results():
    with httpx.Client(transport=httpx.MockTransport(response_for)) as client:
        result = BaiduMcpProvider("test-ak", http_client=client).search_nearby_page(
            query="奶茶",
            latitude=30.57,
            longitude=104.06,
            radius_meters=800,
        )

    assert result.total == 1
    assert result.pois[0].uid == "poi-1"
    assert result.pois[0].tag == "美食;饮品店;奶茶店"
    assert result.pois[0].rating == 4.6
    assert result.pois[0].comment_count == 42
    assert result.pois[0].average_price == 18
    assert result.provider == "baidu_mcp"
    assert result.pagination_supported is False


def test_mcp_provider_normalizes_place_details_and_route_matrix():
    seen_methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method = body["method"]
        seen_methods.append(method)
        if method == "initialize":
            return httpx.Response(
                200,
                headers={"MCP-Session-Id": "session-1"},
                json={"jsonrpc": "2.0", "id": body["id"], "result": {}},
            )
        if method == "notifications/initialized":
            assert request.headers["MCP-Session-Id"] == "session-1"
            return httpx.Response(202)
        assert request.headers["MCP-Session-Id"] == "session-1"
        name = body["params"]["name"]
        if name == "map_place_details":
            value = {"status": 0, "result": MCP_RESULT["results"][0]}
        elif name == "map_directions_matrix":
            value = {
                "status": 0,
                "result": [
                    {
                        "distance": {"value": 2646},
                        "duration": {"value": 368},
                    }
                ],
            }
        else:
            raise AssertionError(name)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "content": [{"type": "text", "text": json.dumps(value)}],
                    "isError": False,
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = BaiduMcpProvider("test-ak", http_client=client)
        detail = provider.place_details(uid="poi-1")
        matrix = provider.directions_matrix(
            origins="30.57,104.06",
            destinations="30.58,104.07",
        )

    assert detail.uid == "poi-1"
    assert detail.rating == 4.6
    assert matrix.mode == "driving"
    assert matrix.routes[0].distance_meters == 2646
    assert matrix.routes[0].duration_seconds == 368
    assert seen_methods == ["initialize", "notifications/initialized", "tools/call", "tools/call"]


def test_mcp_provider_maps_ip_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "content": [{"type": "text", "text": "Authentication failed: APP IP校验失败"}],
                    "isError": True,
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(BaiduMapResponseError) as error:
            BaiduMcpProvider("test-ak", http_client=client).search_region_page(
                query="奶茶", region="成都市"
            )

    assert error.value.kind == "ip_restriction"
    assert not error.value.retryable


def test_mcp_provider_rejects_invalid_coordinates():
    invalid = dict(MCP_RESULT)
    invalid["results"] = [{"uid": "bad", "name": "bad", "location": {"lat": "nan", "lng": 104}}]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"result": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        return httpx.Response(200, json={"result": {"content": [{"type": "text", "text": json.dumps(invalid)}]}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = BaiduMcpProvider("test-ak", http_client=client).search_region_page(query="x", region="y")
    assert result.pois == []
