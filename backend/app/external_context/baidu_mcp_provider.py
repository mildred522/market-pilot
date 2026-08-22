from __future__ import annotations

import json
from math import isfinite
from typing import Any

import httpx

from app.external_context.baidu_client import (
    BaiduGeocodeResult,
    BaiduMapConfigurationError,
    BaiduMapErrorKind,
    BaiduMapResponseError,
    BaiduPlaceSuggestion,
)
from app.external_context.contracts import (
    BaiduPoi,
    BaiduPoiSearchResult,
    BaiduRouteMatrixItem,
    BaiduRouteMatrixResult,
)
from app.services import runtime_config as runtime_config_module

DEFAULT_ENDPOINT = "https://mcp.map.baidu.com/mcp"
MCP_PROTOCOL_VERSION = "2025-03-26"
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


class BaiduMcpProvider:
    """Baidu Maps MCP adapter normalized to the existing map contracts."""

    def __init__(
        self,
        ak: str,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        http_client: httpx.Client | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        if not ak.strip():
            raise BaiduMapConfigurationError("Baidu MCP API key is required")
        if not endpoint.strip():
            raise BaiduMapConfigurationError("Baidu MCP endpoint is required")
        self._ak = ak.strip()
        self._endpoint = endpoint.strip()
        self._http_client = http_client
        self._timeout_seconds = timeout_seconds
        self._initialized = False
        self._session_id: str | None = None
        self._request_id = 0

    @classmethod
    def from_env(
        cls, *, http_client: httpx.Client | None = None
    ) -> "BaiduMcpProvider":
        return cls(
            runtime_config_module.runtime_config.get("baidu_api_key", "BAIDU_MAP_AK"),
            endpoint=runtime_config_module.runtime_config.get(
                "baidu_mcp_url",
                "BAIDU_MAP_MCP_URL",
                DEFAULT_ENDPOINT,
            ),
            http_client=http_client,
            timeout_seconds=float(
                runtime_config_module.runtime_config.get(
                    "baidu_mcp_timeout_seconds",
                    "BAIDU_MAP_MCP_TIMEOUT_SECONDS",
                    "15",
                )
            ),
        )

    def geocode(self, *, address: str, city: str) -> BaiduGeocodeResult:
        payload = self._call_tool(
            "map_geocode",
            {
                "address": address,
                "city": city,
                "is_chinese_mainland": "true",
            },
        )
        try:
            location = payload["result"]["location"]
            latitude = float(location["lat"])
            longitude = float(location["lng"])
        except (KeyError, TypeError, ValueError):
            raise BaiduMapResponseError(
                "Baidu MCP geocoding returned an invalid location",
                kind=BaiduMapErrorKind.REQUEST,
            ) from None
        if (
            not isfinite(latitude)
            or not -90 <= latitude <= 90
            or not isfinite(longitude)
            or not -180 <= longitude <= 180
        ):
            raise BaiduMapResponseError(
                "Baidu MCP geocoding returned an invalid location",
                kind=BaiduMapErrorKind.REQUEST,
            )
        return BaiduGeocodeResult(
            latitude=latitude,
            longitude=longitude,
            source="baidu_mcp_geocoding",
        )

    def suggest_places(
        self,
        *,
        query: str,
        region: str,
        city_limit: bool = True,
    ) -> list[BaiduPlaceSuggestion]:
        if not query.strip() or not region.strip():
            raise ValueError("suggestion query and region are required")
        payload = self._call_tool(
            "map_search_places",
            {
                "query": query,
                "region": region,
                "is_chinese_mainland": "true",
            },
        )
        suggestions: list[BaiduPlaceSuggestion] = []
        for item in payload.get("results", []):
            if not isinstance(item, dict) or not str(item.get("name") or "").strip():
                continue
            suggestions.append(
                BaiduPlaceSuggestion(
                    name=str(item["name"]),
                    city=str(item.get("city") or ""),
                    district=str(item.get("area") or ""),
                    adcode=str(item.get("town_code") or ""),
                )
            )
        return suggestions

    def search_nearby_page(
        self,
        *,
        query: str,
        latitude: float,
        longitude: float,
        radius_meters: int,
        page_num: int = 0,
        page_size: int = 20,
        radius_limit: bool = True,
        scope: int = 2,
        coord_type: int = 3,
        filter: str | None = "industry_type:cater",
    ) -> BaiduPoiSearchResult:
        _validate_page(page_num, page_size)
        if page_num > 0:
            return BaiduPoiSearchResult(
                query=query,
                center_latitude=latitude,
                center_longitude=longitude,
                radius_meters=radius_meters,
                page_num=page_num,
                page_size=page_size,
                total=0,
                pois=[],
                pagination_supported=False,
                provider="baidu_mcp",
                provider_warning="MCP search does not expose WebAPI pagination",
            )
        payload = self._call_tool(
            "map_search_places",
            {
                "query": query,
                "location": f"{latitude},{longitude}",
                "radius": radius_meters,
                "region": "全国",
                "is_chinese_mainland": "true",
            },
        )
        return self._build_result(
            payload,
            query=query,
            center_latitude=latitude,
            center_longitude=longitude,
            radius_meters=radius_meters,
            page_num=page_num,
            page_size=page_size,
        )

    def search_region_page(
        self,
        *,
        query: str,
        region: str,
        page_num: int = 0,
        page_size: int = 20,
        scope: int = 2,
        coord_type: int = 3,
        filter: str | None = "industry_type:cater",
    ) -> BaiduPoiSearchResult:
        _validate_page(page_num, page_size)
        if page_num > 0:
            return BaiduPoiSearchResult(
                query=query,
                region=region,
                page_num=page_num,
                page_size=page_size,
                total=0,
                pois=[],
                pagination_supported=False,
                provider="baidu_mcp",
                provider_warning="MCP search does not expose WebAPI pagination",
            )
        payload = self._call_tool(
            "map_search_places",
            {
                "query": query,
                "region": region,
                "is_chinese_mainland": "true",
            },
        )
        return self._build_result(
            payload,
            query=query,
            region=region,
            page_num=page_num,
            page_size=page_size,
        )

    def place_details(self, *, uid: str) -> BaiduPoi:
        payload = self._call_tool(
            "map_place_details",
            {"uid": uid, "is_chinese_mainland": "true"},
        )
        try:
            return self._normalize_poi(payload["result"])
        except (KeyError, TypeError, ValueError):
            raise BaiduMapResponseError(
                "Baidu MCP place details returned an invalid POI",
                kind=BaiduMapErrorKind.REQUEST,
            ) from None

    def directions_matrix(
        self,
        *,
        origins: str,
        destinations: str,
        mode: str = "driving",
    ) -> BaiduRouteMatrixResult:
        if mode not in {"driving", "riding", "walking"}:
            raise ValueError("mode must be driving, riding, or walking")
        payload = self._call_tool(
            "map_directions_matrix",
            {
                "origins": origins,
                "destinations": destinations,
                "model": mode,
            },
        )
        try:
            routes = [
                BaiduRouteMatrixItem(
                    distance_meters=int(item["distance"]["value"]),
                    duration_seconds=int(item["duration"]["value"]),
                )
                for item in payload["result"]
            ]
            return BaiduRouteMatrixResult(mode=mode, routes=routes)
        except (KeyError, TypeError, ValueError):
            raise BaiduMapResponseError(
                "Baidu MCP directions matrix returned an invalid result",
                kind=BaiduMapErrorKind.REQUEST,
            ) from None

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        result = self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        texts = [
            item.get("text", "")
            for item in result.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        if result.get("isError"):
            self._raise_tool_error(" ".join(texts))
        if not texts:
            raise BaiduMapResponseError(
                "Baidu MCP returned empty tool content",
                kind=BaiduMapErrorKind.REQUEST,
            )
        try:
            payload = json.loads(texts[0])
        except json.JSONDecodeError:
            raise BaiduMapResponseError(
                "Baidu MCP returned invalid JSON tool content",
                kind=BaiduMapErrorKind.REQUEST,
            ) from None
        if not isinstance(payload, dict):
            raise BaiduMapResponseError(
                "Baidu MCP returned invalid tool payload",
                kind=BaiduMapErrorKind.REQUEST,
            )
        provider_status = payload.get("status", 0)
        if provider_status != 0:
            self._raise_tool_error(
                str(payload.get("message", "provider error")),
                status=_optional_int(provider_status),
            )
        return payload

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "market-pilot", "version": "0.1"},
            },
        )
        self._request("notifications/initialized", {}, notification=True)
        self._initialized = True

    def _request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        notification: bool = False,
    ) -> dict[str, Any]:
        self._request_id += 1
        body: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        if not notification:
            body["id"] = self._request_id

        headers = dict(MCP_HEADERS)
        if self._session_id:
            headers["MCP-Session-Id"] = self._session_id
        try:
            response = self._post(body, headers)
            response.raise_for_status()
            self._session_id = response.headers.get("MCP-Session-Id") or self._session_id
            if notification or not response.content:
                return {}
            value = _parse_response(response)
        except httpx.TimeoutException:
            raise BaiduMapResponseError(
                "Baidu MCP request timed out",
                kind=BaiduMapErrorKind.RETRYABLE,
                retryable=True,
            ) from None
        except httpx.NetworkError:
            raise BaiduMapResponseError(
                "Baidu MCP network request failed",
                kind=BaiduMapErrorKind.RETRYABLE,
                retryable=True,
            ) from None
        except httpx.HTTPStatusError as error:
            kind = (
                BaiduMapErrorKind.RETRYABLE
                if error.response.status_code >= 500
                else BaiduMapErrorKind.REQUEST
            )
            raise BaiduMapResponseError(
                "Baidu MCP returned an HTTP error",
                provider_status=error.response.status_code,
                kind=kind,
                retryable=kind == BaiduMapErrorKind.RETRYABLE,
            ) from None
        except httpx.RequestError:
            raise BaiduMapResponseError(
                "Baidu MCP request failed",
                kind=BaiduMapErrorKind.REQUEST,
            ) from None
        except (TypeError, ValueError):
            raise BaiduMapResponseError(
                "Baidu MCP returned invalid JSON",
                kind=BaiduMapErrorKind.REQUEST,
            ) from None

        if "error" in value:
            error = value["error"]
            message = error.get("message", "JSON-RPC error") if isinstance(error, dict) else "JSON-RPC error"
            raise BaiduMapResponseError(
                f"Baidu MCP JSON-RPC request failed: {message}",
                kind=BaiduMapErrorKind.REQUEST,
            )
        result = value.get("result", {})
        if not isinstance(result, dict):
            raise BaiduMapResponseError(
                "Baidu MCP returned invalid result",
                kind=BaiduMapErrorKind.REQUEST,
            )
        return result

    def _post(self, body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        if self._http_client is not None:
            return self._http_client.post(
                self._endpoint,
                params={"ak": self._ak},
                json=body,
                headers=headers,
                timeout=self._timeout_seconds,
            )
        with httpx.Client() as client:
            return client.post(
                self._endpoint,
                params={"ak": self._ak},
                json=body,
                headers=headers,
                timeout=self._timeout_seconds,
            )

    def _raise_tool_error(self, message: str, *, status: int | None = None) -> None:
        lowered = message.lower()
        if "ip" in lowered or "校验" in message:
            kind = BaiduMapErrorKind.IP_RESTRICTION
        elif "authentication" in lowered or "ak" in lowered:
            kind = BaiduMapErrorKind.AUTHENTICATION
        elif "quota" in lowered or "配额" in message:
            kind = BaiduMapErrorKind.QUOTA
        elif "permission" in lowered or "权限" in message:
            kind = BaiduMapErrorKind.PERMISSION
        else:
            kind = BaiduMapErrorKind.UNKNOWN
        raise BaiduMapResponseError(
            f"Baidu MCP tool failed: {message}",
            provider_status=status,
            kind=kind,
        )

    @staticmethod
    def _normalize_poi(item: dict[str, Any]) -> BaiduPoi:
        location = item["location"]
        latitude = float(location["lat"])
        longitude = float(location["lng"])
        if (
            not isfinite(latitude)
            or not -90 <= latitude <= 90
            or not isfinite(longitude)
            or not -180 <= longitude <= 180
        ):
            raise ValueError("POI coordinate out of range")
        detail = item.get("detail_info") or {}
        return BaiduPoi(
            uid=str(item["uid"]),
            name=str(item["name"]),
            latitude=latitude,
            longitude=longitude,
            address=str(item.get("address") or ""),
            business_status=str(item.get("status") or ""),
            distance_meters=_optional_int(detail.get("distance")),
            tag=detail.get("classified_poi_tag") or detail.get("tag"),
            brand=detail.get("brand"),
            rating=_optional_float(detail.get("overall_rating")),
            comment_count=_optional_int(detail.get("comment_num")),
            average_price=_optional_float(detail.get("price")),
        )

    @staticmethod
    def _build_result(
        payload: dict[str, Any],
        *,
        query: str,
        page_num: int,
        page_size: int,
        center_latitude: float | None = None,
        center_longitude: float | None = None,
        radius_meters: int | None = None,
        region: str | None = None,
    ) -> BaiduPoiSearchResult:
        pois: list[BaiduPoi] = []
        for item in payload.get("results", []):
            if not isinstance(item, dict):
                continue
            try:
                pois.append(BaiduMcpProvider._normalize_poi(item))
            except (KeyError, TypeError, ValueError):
                continue
        return BaiduPoiSearchResult(
            query=query,
            center_latitude=center_latitude,
            center_longitude=center_longitude,
            radius_meters=radius_meters,
            region=region,
            page_num=page_num,
            page_size=page_size,
            total=int(payload.get("total", len(pois))),
            pois=pois,
            pagination_supported=False,
            provider="baidu_mcp",
            provider_warning="MCP search does not expose WebAPI pagination",
        )


def _parse_response(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "").lower()
    if "text/event-stream" not in content_type:
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("MCP response must be an object")
        return value

    messages: list[dict[str, Any]] = []
    data_lines: list[str] = []
    for line in response.text.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif not line.strip() and data_lines:
            _append_sse_message(messages, data_lines)
            data_lines = []
    if data_lines:
        _append_sse_message(messages, data_lines)
    if not messages:
        raise ValueError("empty MCP event stream")
    return messages[-1]


def _append_sse_message(messages: list[dict[str, Any]], data_lines: list[str]) -> None:
    value = json.loads("\n".join(data_lines))
    if isinstance(value, dict):
        messages.append(value)


def _validate_page(page_num: int, page_size: int) -> None:
    if isinstance(page_num, bool) or not isinstance(page_num, int) or page_num < 0:
        raise ValueError("page_num must be non-negative")
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= 20
    ):
        raise ValueError("page_size must be between 1 and 20")


def _optional_int(value: Any) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
