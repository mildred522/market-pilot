from __future__ import annotations

import os
from pathlib import Path
from threading import RLock

from app.services.secret_store import EncryptedSecretStore, WindowsDpapiProtector


class RuntimeConfigStore:
    def __init__(self, secret_store: EncryptedSecretStore | None = None) -> None:
        self._values: dict[str, str] = {}
        self._lock = RLock()
        self._secret_store = secret_store
        if secret_store is not None:
            try:
                self._values.update(secret_store.load())
            except (OSError, ValueError, UnicodeError):
                # A damaged or foreign-user DPAPI file must not prevent startup.
                self._values = {}

    def set_baidu_key(self, api_key: str) -> None:
        self._update({"baidu_api_key": self._normalize_secret(api_key)})

    def set_agent(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        provider: str,
    ) -> None:
        values = {
            "agent_api_key": self._normalize_secret(api_key),
            "agent_model": model,
            "agent_base_url": base_url,
            "agent_provider": provider,
        }
        self._update({key: value.strip() for key, value in values.items()})

    def clear(self, integration: str) -> None:
        prefixes = {
            "baidu": ("baidu_",),
            "agent": ("agent_",),
        }[integration]
        with self._lock:
            previous = self._values.copy()
            for key in list(self._values):
                if key.startswith(prefixes):
                    self._values.pop(key, None)
            try:
                self._persist_locked()
            except Exception:
                self._values = previous
                raise

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

    def _normalize_secret(self, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("API key cannot be empty")
        return normalized

    def _update(self, values: dict[str, str]) -> None:
        with self._lock:
            previous = self._values.copy()
            self._values.update(values)
            try:
                self._persist_locked()
            except Exception:
                self._values = previous
                raise

    def _persist_locked(self) -> None:
        if self._secret_store is not None:
            self._secret_store.save(self._values)

    def _source(self, key: str, env_name: str) -> str | None:
        with self._lock:
            if self._values.get(key, "").strip():
                return "saved" if self._secret_store is not None else "runtime"
        if os.getenv(env_name, "").strip():
            return "environment"
        return None


def _default_secret_store() -> EncryptedSecretStore | None:
    if os.name != "nt":
        return None
    configured_path = os.getenv("MARKET_PILOT_CONFIG_PATH", "").strip()
    path = (
        Path(configured_path)
        if configured_path
        else Path(__file__).resolve().parents[2]
        / "storage"
        / "integration_config.dpapi"
    )
    return EncryptedSecretStore(path, WindowsDpapiProtector())


runtime_config = RuntimeConfigStore(_default_secret_store())
