from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .engine import run_demo, run_demo_from_csv
from .ingestion import inspect_csv


WEB_ROOT = Path(__file__).resolve().parent / "web"


def llm_config_status() -> dict[str, object]:
    endpoint = os.getenv("PLAN_EXECUTE_LLM_URL", "").strip()
    model = os.getenv("PLAN_EXECUTE_LLM_MODEL", "").strip()
    api_key = os.getenv("PLAN_EXECUTE_LLM_API_KEY", "").strip()
    return {"configured": bool(endpoint and model and api_key), "endpoint": endpoint, "model": model}


def configure_llm(payload: dict[str, Any]) -> dict[str, object]:
    endpoint = str(payload.get("endpoint") or "").strip()
    model = str(payload.get("model") or "").strip()
    api_key = str(payload.get("api_key") or "").strip()
    if not endpoint.startswith("https://"):
        raise ValueError("llm_endpoint_must_use_https")
    if not model:
        raise ValueError("llm_model_required")
    os.environ["PLAN_EXECUTE_LLM_URL"] = endpoint
    os.environ["PLAN_EXECUTE_LLM_MODEL"] = model
    if api_key:
        os.environ["PLAN_EXECUTE_LLM_API_KEY"] = api_key
    return llm_config_status()


def api_response(path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    try:
        if path == "/api/llm-config":
            return HTTPStatus.OK, configure_llm(payload)
        if path == "/api/inspect":
            return HTTPStatus.OK, inspect_csv(str(payload["csv"]), str(payload["kind"]))
        if path == "/api/analyze":
            question = str(payload.get("question") or "做一次完整经营体检")
            mode = str(payload.get("mode") or "focused")
            if payload.get("orders_csv") and payload.get("menu_csv"):
                report = run_demo_from_csv(
                    question,
                    mode=mode,
                    orders_csv=str(payload["orders_csv"]),
                    menu_csv=str(payload["menu_csv"]),
                    orders_mapping=payload.get("orders_mapping"),
                    menu_mapping=payload.get("menu_mapping"),
                )
            else:
                report = run_demo(question, mode=mode)
            return HTTPStatus.OK, report.as_dict()
        return HTTPStatus.NOT_FOUND, {"error": "unknown_api_path"}
    except (KeyError, TypeError, ValueError) as error:
        return HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)}


class DemoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return
        status, response = api_response(self.path, payload)
        self._send_json(status, response)

    def do_GET(self) -> None:
        if self.path == "/api/llm-config":
            self._send_json(HTTPStatus.OK, llm_config_status())
            return
        super().do_GET()

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8765), DemoHandler)
    print("Plan-Execute demo: http://127.0.0.1:8765")
    server.serve_forever()


if __name__ == "__main__":
    main()
