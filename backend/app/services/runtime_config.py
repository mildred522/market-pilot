from __future__ import annotations

import os
from threading import RLock


class RuntimeConfigStore:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._lock = RLock()

    def set_baidu_key(self, api_key: str) -> None:
        self._set("baidu_api_key", api_key)

    def set_agent(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        provider: str,
    ) -> None:
        values = {
            "agent_api_key": api_key,
            "agent_model": model,
            "agent_base_url": base_url,
            "agent_provider": provider,
        }
        with self._lock:
            self._values.update({key: value.strip() for key, value in values.items()})

    def clear(self, integration: str) -> None:
        prefixes = {
            "baidu": ("baidu_",),
            "agent": ("agent_",),
        }[integration]
        with self._lock:
            for key in list(self._values):
                if key.startswith(prefixes):
                    self._values.pop(key, None)

    def get(self, key: str, env_name: str, default: str = "") -> str:
        with self._lock:
            runtime_value = self._values.get(key, "").strip()
        return runtime_value or os.getenv(env_name, default).strip()

    def status(self) -> dict[str, dict[str, object]]:
        baidu_source = self._source("baidu_api_key", "BAIDU_MAP_AK")
        agent_key_source = self._source("agent_api_key", "AGENT_LLM_API_KEY")
        model = self.get("agent_model", "AGENT_LLM_MODEL")
        return {
            "baidu": {
                "configured": bool(self.get("baidu_api_key", "BAIDU_MAP_AK")),
                "source": baidu_source,
            },
            "agent": {
                "configured": bool(agent_key_source and model),
                "source": agent_key_source,
                "model": model or None,
                "provider": self.get(
                    "agent_provider", "AGENT_LLM_PROVIDER", "openai-compatible"
                ),
                "base_url": self.get(
                    "agent_base_url",
                    "AGENT_LLM_BASE_URL",
                    "https://api.openai.com/v1",
                ),
            },
        }

    def _set(self, key: str, value: str) -> None:
        normalized = value.strip()
        if not normalized:
            raise ValueError("API key cannot be empty")
        with self._lock:
            self._values[key] = normalized

    def _source(self, key: str, env_name: str) -> str | None:
        with self._lock:
            if self._values.get(key, "").strip():
                return "runtime"
        if os.getenv(env_name, "").strip():
            return "environment"
        return None


runtime_config = RuntimeConfigStore()
