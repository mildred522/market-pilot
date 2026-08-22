from __future__ import annotations

from typing import Protocol

from app.external_context.baidu_client import (
    BaiduGeocodeResult,
    BaiduMapClient,
    BaiduPlaceSuggestion,
)
from app.external_context.contracts import (
    BaiduPoi,
    BaiduPoiSearchResult,
    BaiduRouteMatrixResult,
)


class BaiduWebApiProvider(BaiduMapClient):
    """Named WebAPI provider; behavior remains the existing client behavior."""


class LocationProvider(Protocol):
    """Core map capabilities shared by WebAPI and MCP providers."""

    def geocode(self, *, address: str, city: str) -> BaiduGeocodeResult: ...

    def suggest_places(
        self, *, query: str, region: str, city_limit: bool = True
    ) -> list[BaiduPlaceSuggestion]: ...

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
    ) -> BaiduPoiSearchResult: ...

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
    ) -> BaiduPoiSearchResult: ...


class LocationEnrichmentProvider(Protocol):
    """Optional detail and route capabilities exposed by selected providers."""

    def place_details(self, *, uid: str) -> BaiduPoi: ...

    def directions_matrix(
        self,
        *,
        origins: str,
        destinations: str,
        mode: str = "driving",
    ) -> BaiduRouteMatrixResult: ...


class FallbackLocationProvider:
    """Use the secondary provider only for retryable primary failures."""

    def __init__(self, primary: LocationProvider, fallback: LocationProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    def _call(self, method: str, **kwargs):
        primary_method = getattr(self._primary, method, None)
        if primary_method is None:
            return getattr(self._fallback, method)(**kwargs)
        try:
            return primary_method(**kwargs)
        except Exception as error:
            from app.external_context.baidu_client import BaiduMapResponseError

            if not isinstance(error, BaiduMapResponseError) or not error.retryable:
                raise
            result = getattr(self._fallback, method)(**kwargs)
            if isinstance(result, BaiduPoiSearchResult):
                primary_warning = (
                    f"primary provider failed retryably: {error.kind.value}"
                )
                warning = "; ".join(
                    value
                    for value in (primary_warning, result.provider_warning)
                    if value
                )
                return result.model_copy(update={"provider_warning": warning})
            return result

    def geocode(self, **kwargs):
        return self._call("geocode", **kwargs)

    def suggest_places(self, **kwargs):
        return self._call("suggest_places", **kwargs)

    def search_nearby_page(self, **kwargs):
        return self._call("search_nearby_page", **kwargs)

    def search_region_page(self, **kwargs):
        return self._call("search_region_page", **kwargs)

    def place_details(self, **kwargs):
        return self._call("place_details", **kwargs)

    def directions_matrix(self, **kwargs):
        return self._call("directions_matrix", **kwargs)
