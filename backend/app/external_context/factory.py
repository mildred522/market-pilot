from __future__ import annotations

from typing import Callable

from app.external_context.baidu_client import BaiduMapConfigurationError
from app.external_context.baidu_mcp_provider import BaiduMcpProvider
from app.external_context.provider import (
    BaiduWebApiProvider,
    FallbackLocationProvider,
    LocationProvider,
)
from app.services import runtime_config as runtime_config_module


def get_location_provider_factory() -> Callable[[], LocationProvider]:
    def factory() -> LocationProvider:
        runtime_config = runtime_config_module.runtime_config
        mode = runtime_config.get(
            "baidu_provider", "BAIDU_MAP_PROVIDER", "webapi"
        ).lower()
        if mode == "mcp":
            return BaiduMcpProvider.from_env()
        if mode == "webapi":
            return BaiduWebApiProvider.from_env()
        if mode == "webapi_with_mcp_fallback":
            return FallbackLocationProvider(
                BaiduWebApiProvider.from_env(),
                BaiduMcpProvider.from_env(),
            )
        raise BaiduMapConfigurationError(
            "BAIDU_MAP_PROVIDER must be webapi, mcp, or webapi_with_mcp_fallback"
        )

    return factory
