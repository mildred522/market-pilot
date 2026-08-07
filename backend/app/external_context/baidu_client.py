import os
from typing import Any

import httpx

from app.external_context.contracts import BaiduPoi, BaiduPoiSearchResult


class BaiduMapConfigurationError(ValueError):
    pass


class BaiduMapResponseError(RuntimeError):
    pass


class BaiduMapClient:
    BASE_URL = "https://api.map.baidu.com/place/v2/search"

    def __init__(
        self,
        ak: str,
        *,
        http_client: httpx.Client | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not ak.strip():
            raise BaiduMapConfigurationError("Baidu server API key is required")
        self._ak = ak
        self._http_client = http_client
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_env(
        cls,
        *,
        http_client: httpx.Client | None = None,
    ) -> "BaiduMapClient":
        ak = os.getenv("BAIDU_MAP_AK", "")
        if not ak.strip():
            raise BaiduMapConfigurationError(
                "BAIDU_MAP_AK is required for Baidu Place API"
            )
        return cls(ak, http_client=http_client)

    def search_nearby(
        self,
        *,
        query: str,
        latitude: float,
        longitude: float,
        radius_meters: int,
    ) -> BaiduPoiSearchResult:
        return self.search_nearby_page(
            query=query,
            latitude=latitude,
            longitude=longitude,
            radius_meters=radius_meters,
        )

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
        self._validate_page(page_num, page_size)
        params: dict[str, str | int] = {
            "query": query,
            "location": f"{latitude},{longitude}",
            "radius": radius_meters,
            "radius_limit": str(radius_limit).lower(),
            "output": "json",
            "scope": scope,
            "coord_type": coord_type,
            "page_size": page_size,
            "page_num": page_num,
            "ak": self._ak,
        }
        if filter is not None:
            params["filter"] = filter
        payload = self._execute(params)
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
        self._validate_page(page_num, page_size)
        params: dict[str, str | int] = {
            "query": query,
            "region": region,
            "output": "json",
            "scope": scope,
            "coord_type": coord_type,
            "page_size": page_size,
            "page_num": page_num,
            "ak": self._ak,
        }
        if filter is not None:
            params["filter"] = filter
        payload = self._execute(params)
        return self._build_result(
            payload,
            query=query,
            region=region,
            page_num=page_num,
            page_size=page_size,
        )

    def _execute(self, params: dict[str, str | int]) -> dict[str, Any]:
        if self._http_client is not None:
            payload = self._request(self._http_client, params)
        else:
            with httpx.Client() as http_client:
                payload = self._request(http_client, params)

        status = payload.get("status")
        if status != 0:
            message = payload.get("message", "unknown provider error")
            safe_message = str(message).replace(self._ak, "[redacted]")
            raise BaiduMapResponseError(
                f"Baidu Place API status={status}: {safe_message}"
            )
        return payload

    def _build_result(
        self,
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
        pois = [
            self._normalize_poi(item)
            for item in payload.get("results", [])
        ]
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
        )

    @staticmethod
    def _validate_page(page_num: int, page_size: int) -> None:
        if page_num < 0:
            raise ValueError("page_num must be non-negative")
        if not 1 <= page_size <= 20:
            raise ValueError("page_size must be between 1 and 20")

    def _request(
        self,
        http_client: httpx.Client,
        params: dict[str, str | int],
    ) -> dict[str, Any]:
        try:
            response = http_client.get(
                self.BASE_URL,
                params=params,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            raise BaiduMapResponseError("Baidu Place API request failed") from None
        if not isinstance(payload, dict):
            raise BaiduMapResponseError("Baidu Place API returned invalid JSON")
        return payload

    @staticmethod
    def _normalize_poi(item: dict[str, Any]) -> BaiduPoi:
        location = item["location"]
        detail = item.get("detail_info") or {}
        return BaiduPoi(
            uid=str(item["uid"]),
            name=str(item["name"]),
            latitude=float(location["lat"]),
            longitude=float(location["lng"]),
            address=str(item.get("address") or ""),
            business_status=str(item.get("status") or ""),
            distance_meters=_optional_int(detail.get("distance")),
            tag=_optional_text(detail.get("tag")),
            brand=_optional_text(detail.get("brand")),
            rating=_optional_float(detail.get("overall_rating")),
            comment_count=_optional_int(detail.get("comment_num")),
            average_price=_optional_float(detail.get("price")),
        )


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
