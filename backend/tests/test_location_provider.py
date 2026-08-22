import pytest

from app.external_context.baidu_client import BaiduMapErrorKind, BaiduMapResponseError
from app.external_context.factory import get_location_provider_factory
from app.external_context.provider import (
    BaiduWebApiProvider,
    FallbackLocationProvider,
)


class Provider:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = 0

    def geocode(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise BaiduMapResponseError("temporary", kind=BaiduMapErrorKind.RETRYABLE, retryable=True)
        return "fallback-result"


def test_fallback_uses_secondary_provider_for_retryable_failure():
    primary = Provider(fail=True)
    secondary = Provider()
    result = FallbackLocationProvider(primary, secondary).geocode(address="x", city="y")
    assert result == "fallback-result"
    assert primary.calls == 1
    assert secondary.calls == 1


def test_fallback_preserves_mcp_pagination_warning():
    from app.external_context.contracts import BaiduPoiSearchResult

    class Primary:
        def search_region_page(self, **kwargs):
            raise BaiduMapResponseError(
                "temporary",
                kind=BaiduMapErrorKind.RETRYABLE,
                retryable=True,
            )

    class Secondary:
        def search_region_page(self, **kwargs):
            return BaiduPoiSearchResult(
                query="x",
                region="y",
                total=1,
                pois=[],
                pagination_supported=False,
                provider="baidu_mcp",
                provider_warning="MCP search does not expose WebAPI pagination",
            )

    result = FallbackLocationProvider(Primary(), Secondary()).search_region_page(
        query="x", region="y"
    )
    assert "primary provider failed retryably" in result.provider_warning
    assert "pagination" in result.provider_warning


def test_provider_factory_defaults_to_webapi(monkeypatch):
    monkeypatch.delenv("BAIDU_MAP_PROVIDER", raising=False)
    monkeypatch.setenv("BAIDU_MAP_AK", "test-api-key")
    provider = get_location_provider_factory()()
    assert isinstance(provider, BaiduWebApiProvider)


def test_fallback_does_not_hide_permanent_failure():
    class Permanent(Provider):
        def geocode(self, **kwargs):
            raise BaiduMapResponseError("denied", kind=BaiduMapErrorKind.PERMISSION)

    with pytest.raises(BaiduMapResponseError):
        FallbackLocationProvider(Permanent(), Provider()).geocode(address="x", city="y")
