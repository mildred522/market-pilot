import os
from enum import Enum
from typing import Any

import httpx
from pydantic import BaseModel

from app.external_context.contracts import BaiduPoi, BaiduPoiSearchResult


class BaiduMapConfigurationError(ValueError):
    pass


class BaiduMapErrorKind(str, Enum):
    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    IP_RESTRICTION = "ip_restriction"
    SIGNATURE = "signature"
    PERMISSION = "permission"
    QUOTA = "quota"
    REQUEST = "request"
    RETRYABLE = "retryable"
    UNKNOWN = "unknown"


class BaiduMapResponseError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider_status: int | None = None,
        kind: BaiduMapErrorKind = BaiduMapErrorKind.UNKNOWN,
        retryable: bool | None = None,
    ) -> None:
        self.provider_status = provider_status
        self.kind = BaiduMapErrorKind(kind)
        self.retryable = (
            self.kind == BaiduMapErrorKind.RETRYABLE
            if retryable is None
            else retryable
        )
        super().__init__(message)


class BaiduGeocodeResult(BaseModel):
    latitude: float
    longitude: float
    coordinate_system: str = "bd09ll"
    source: str = "baidu_geocoding"


_PROVIDER_STATUS_KINDS = {
    1: BaiduMapErrorKind.RETRYABLE,
    2: BaiduMapErrorKind.REQUEST,
    3: BaiduMapErrorKind.PERMISSION,
    4: BaiduMapErrorKind.QUOTA,
    5: BaiduMapErrorKind.AUTHENTICATION,
    101: BaiduMapErrorKind.CONFIGURATION,
    102: BaiduMapErrorKind.PERMISSION,
    200: BaiduMapErrorKind.AUTHENTICATION,
    201: BaiduMapErrorKind.AUTHENTICATION,
    202: BaiduMapErrorKind.AUTHENTICATION,
    203: BaiduMapErrorKind.CONFIGURATION,
    210: BaiduMapErrorKind.IP_RESTRICTION,
    211: BaiduMapErrorKind.SIGNATURE,
    220: BaiduMapErrorKind.PERMISSION,
    240: BaiduMapErrorKind.PERMISSION,
    260: BaiduMapErrorKind.PERMISSION,
    261: BaiduMapErrorKind.PERMISSION,
    301: BaiduMapErrorKind.QUOTA,
    302: BaiduMapErrorKind.QUOTA,
    401: BaiduMapErrorKind.QUOTA,
    402: BaiduMapErrorKind.QUOTA,
}


class BaiduMapClient:
    BASE_URL = "https://api.map.baidu.com/place/v2/search"
    GEOCODING_URL = "https://api.map.baidu.com/geocoding/v3"

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

    def geocode(self, *, address: str, city: str) -> BaiduGeocodeResult:
        payload = self._execute(
            {
                "address": address,
                "city": city,
                "output": "json",
                "ak": self._ak,
            },
            url=self.GEOCODING_URL,
        )
        try:
            location = payload["result"]["location"]
            return BaiduGeocodeResult(
                latitude=float(location["lat"]),
                longitude=float(location["lng"]),
            )
        except (KeyError, TypeError, ValueError):
            raise BaiduMapResponseError(
                "Baidu geocoding returned an invalid location",
                kind=BaiduMapErrorKind.REQUEST,
            ) from None

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

    def _execute(
        self,
        params: dict[str, str | int],
        *,
        url: str | None = None,
    ) -> dict[str, Any]:
        if self._http_client is not None:
            payload = self._request(self._http_client, params, url=url)
        else:
            with httpx.Client() as http_client:
                payload = self._request(http_client, params, url=url)

        status = _optional_int(payload.get("status"))
        if status != 0:
            message = payload.get("message", "unknown provider error")
            safe_message = str(message).replace(self._ak, "[redacted]")
            raise BaiduMapResponseError(
                f"Baidu Place API status={status}: {safe_message}",
                provider_status=status,
                kind=_PROVIDER_STATUS_KINDS.get(
                    status, BaiduMapErrorKind.UNKNOWN
                ),
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
        if (
            isinstance(page_num, bool)
            or not isinstance(page_num, int)
            or page_num < 0
        ):
            raise ValueError("page_num must be non-negative")
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= 20
        ):
            raise ValueError("page_size must be between 1 and 20")

    def _request(
        self,
        http_client: httpx.Client,
        params: dict[str, str | int],
        *,
        url: str | None = None,
    ) -> dict[str, Any]:
        try:
            response = http_client.get(
                url or self.BASE_URL,
                params=params,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException:
            raise BaiduMapResponseError(
                "Baidu Place API request timed out",
                kind=BaiduMapErrorKind.RETRYABLE,
                retryable=True,
            ) from None
        except httpx.NetworkError:
            raise BaiduMapResponseError(
                "Baidu Place API network request failed",
                kind=BaiduMapErrorKind.RETRYABLE,
                retryable=True,
            ) from None
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            kind = _http_error_kind(status)
            raise BaiduMapResponseError(
                "Baidu Place API returned an HTTP error",
                provider_status=status,
                kind=kind,
                retryable=kind == BaiduMapErrorKind.RETRYABLE,
            ) from None
        except httpx.RequestError:
            raise BaiduMapResponseError(
                "Baidu Place API request failed",
                kind=BaiduMapErrorKind.REQUEST,
            ) from None
        except ValueError:
            raise BaiduMapResponseError(
                "Baidu Place API returned invalid JSON",
                kind=BaiduMapErrorKind.REQUEST,
            ) from None
        if not isinstance(payload, dict):
            raise BaiduMapResponseError(
                "Baidu Place API returned invalid JSON",
                kind=BaiduMapErrorKind.REQUEST,
            )
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


def _http_error_kind(status: int) -> BaiduMapErrorKind:
    if status == 429:
        return BaiduMapErrorKind.QUOTA
    if status == 401:
        return BaiduMapErrorKind.AUTHENTICATION
    if status == 403:
        return BaiduMapErrorKind.PERMISSION
    if status == 408 or status >= 500:
        return BaiduMapErrorKind.RETRYABLE
    return BaiduMapErrorKind.REQUEST


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
