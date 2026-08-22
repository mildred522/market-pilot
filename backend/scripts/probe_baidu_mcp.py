from __future__ import annotations

"""Minimal Baidu Maps MCP probe.

This intentionally stays outside the location runtime. It verifies the remote
MCP transport and response shape before a LocationProvider adapter is added.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    import httpx
except ModuleNotFoundError:  # pragma: no cover - depends on local environment
    httpx = None  # type: ignore[assignment]

DEFAULT_ENDPOINT = "https://mcp.map.baidu.com/mcp"
MCP_PROTOCOL_VERSION = "2025-03-26"


class ProbeError(RuntimeError):
    pass


@dataclass
class McpResponse:
    payload: dict[str, Any]
    session_id: str | None


class BaiduMcpProbe:
    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout_seconds: float = 15.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise ProbeError("BAIDU_MAP_AK is required")
        if httpx is None:
            raise ProbeError("httpx is required; install backend requirements first")
        self._endpoint = _with_api_key(endpoint, api_key)
        self._timeout_seconds = timeout_seconds
        self._client = http_client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = http_client is None
        self._session_id: str | None = None
        self._request_id = 0

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def initialize(self) -> dict[str, Any]:
        return self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "market-pilot-mcp-probe", "version": "0.1"},
            },
        ).payload

    def initialized(self) -> None:
        self._notify("notifications/initialized", {})

    def list_tools(self) -> dict[str, Any]:
        return self._request("tools/list", {}).payload

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
        ).payload

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._session_id:
            headers["MCP-Session-Id"] = self._session_id
        try:
            response = self._client.post(
                self._endpoint,
                headers=headers,
                json={"jsonrpc": "2.0", "method": method, "params": params},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ProbeError(f"MCP notification failed: {error}") from error

    def _request(self, method: str, params: dict[str, Any]) -> McpResponse:
        self._request_id += 1
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._session_id:
            headers["MCP-Session-Id"] = self._session_id
        body = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        try:
            response = self._client.post(
                self._endpoint,
                headers=headers,
                json=body,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ProbeError(f"MCP HTTP request failed: {error}") from error

        self._session_id = (
            response.headers.get("MCP-Session-Id") or self._session_id
        )
        try:
            payload = _parse_mcp_response(response)
        except (ValueError, json.JSONDecodeError) as error:
            raise ProbeError(
                "MCP returned an unsupported response body "
                f"(content-type={response.headers.get('content-type', '')!r})"
            ) from error
        if "error" in payload:
            raise ProbeError(f"MCP method {method} failed: {_compact(payload['error'])}")
        if "result" not in payload:
            raise ProbeError(f"MCP method {method} returned no result")
        return McpResponse(payload=payload["result"], session_id=self._session_id)


def _parse_mcp_response(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "").lower()
    if "text/event-stream" not in content_type:
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("MCP JSON response must be an object")
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


def _with_api_key(endpoint: str, api_key: str) -> str:
    parsed = urlsplit(endpoint)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["ak"] = api_key
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_api_key() -> str:
    value = os.getenv("BAIDU_MAP_AK", "").strip()
    if value:
        return value
    env_path = Path(__file__).resolve().parents[1] / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("BAIDU_MAP_AK="):
                return line.partition("=")[2].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _tool_text(result: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for item in result.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            values.append(str(item.get("text", "")))
    return values


def _print_json(title: str, value: Any) -> None:
    print(f"\n[{title}]")
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe Baidu Maps MCP Server")
    parser.add_argument(
        "--endpoint",
        default=os.getenv("BAIDU_MAP_MCP_URL", DEFAULT_ENDPOINT),
        help="Streamable HTTP endpoint; defaults to BAIDU_MAP_MCP_URL or the official endpoint",
    )
    parser.add_argument("--address", help="Optional address for map_geocode")
    parser.add_argument("--city", default="", help="Optional city label")
    parser.add_argument("--query", help="Optional POI query for map_search_places")
    parser.add_argument("--region", default="", help="Region for the POI query")
    parser.add_argument("--latitude", type=float, help="POI search center latitude")
    parser.add_argument("--longitude", type=float, help="POI search center longitude")
    parser.add_argument("--radius", type=int, default=800, help="POI search radius in meters")
    parser.add_argument("--timeout", type=float, default=15.0)
    arguments = parser.parse_args(argv)

    api_key = _load_api_key()
    try:
        probe = BaiduMcpProbe(
            api_key=api_key,
            endpoint=arguments.endpoint,
            timeout_seconds=arguments.timeout,
        )
    except ProbeError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    try:
        initialize = probe.initialize()
        _print_json("initialize", initialize)
        probe.initialized()
        tools = probe.list_tools()
        names = [
            item.get("name")
            for item in tools.get("tools", [])
            if isinstance(item, dict)
        ]
        _print_json("tools", {"count": len(names), "names": names})

        if arguments.address:
            result = probe.call_tool(
                "map_geocode",
                {"address": arguments.address, "is_china": "true"},
            )
            _print_json(
                "map_geocode",
                {"address": arguments.address, "city": arguments.city, "text": _tool_text(result)},
            )

        if arguments.query:
            if (arguments.latitude is None) != (arguments.longitude is None):
                raise ProbeError("--latitude and --longitude must be provided together")
            params: dict[str, Any] = {
                "query": arguments.query,
                "region": arguments.region or "全国",
                "is_china": "true",
            }
            if arguments.latitude is not None and arguments.longitude is not None:
                params.update(
                    {
                        "location": f"{arguments.latitude},{arguments.longitude}",
                        "radius": arguments.radius,
                    }
                )
            result = probe.call_tool("map_search_places", params)
            _print_json(
                "map_search_places",
                {"arguments": params, "text": _tool_text(result)},
            )
    except ProbeError as error:
        print(f"Probe failed: {error}", file=sys.stderr)
        return 1
    finally:
        probe.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
