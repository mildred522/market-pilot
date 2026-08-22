from __future__ import annotations

import os
from pathlib import Path
from threading import RLock

from app.knowledge.contracts import KnowledgeRagSettings
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

    def baidu_provider(self) -> str:
        return self.get("baidu_provider", "BAIDU_MAP_PROVIDER", "webapi")

    def set_agent(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        provider: str,
        planner_model: str = "",
        synthesizer_model: str = "",
        followup_model: str = "",
    ) -> None:
        values = {
            "agent_api_key": self._normalize_secret(api_key),
            "agent_model": model,
            "agent_base_url": base_url,
            "agent_provider": provider,
            "agent_planner_model": planner_model,
            "agent_synthesizer_model": synthesizer_model,
            "agent_followup_model": followup_model,
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
        knowledge = self.knowledge_rag_settings()
        return {
            "baidu": {
                "configured": bool(self.get("baidu_api_key", "BAIDU_MAP_AK")),
                "source": baidu_source,
            },
            "agent": {
                "configured": bool(agent_key_source and model),
                "source": agent_key_source,
                "model": model or None,
                "role_models": {
                    role: self.agent_model_override(role) or None
                    for role in ("planner", "synthesizer", "followup")
                },
                "effective_role_models": {
                    role: self.agent_model(role) or None
                    for role in ("planner", "synthesizer", "followup")
                },
                "provider": self.get(
                    "agent_provider", "AGENT_LLM_PROVIDER", "openai-compatible"
                ),
                "base_url": self.get(
                    "agent_base_url",
                    "AGENT_LLM_BASE_URL",
                    "https://api.openai.com/v1",
                ),
            },
            "knowledge_rag": {
                "enabled": knowledge.enabled,
                "configured": knowledge.configured,
                "collection": knowledge.collection,
                "dense_model": knowledge.dense_model,
                "reranker_model": (
                    knowledge.reranker_model if knowledge.rerank_enabled else None
                ),
            },
        }

    def knowledge_rag_settings(self) -> KnowledgeRagSettings:
        return KnowledgeRagSettings(
            enabled=_as_bool(
                self.get("knowledge_rag_enabled", "KNOWLEDGE_RAG_ENABLED", "false")
            ),
            qdrant_url=self.get(
                "qdrant_url", "QDRANT_URL", "http://127.0.0.1:6333"
            ),
            qdrant_api_key=self.get("qdrant_api_key", "QDRANT_API_KEY"),
            collection=self.get(
                "qdrant_collection",
                "QDRANT_COLLECTION",
                "market_pilot_knowledge_v1",
            ),
            storage_root=self.get(
                "knowledge_storage_root",
                "KNOWLEDGE_STORAGE_ROOT",
                "./storage/knowledge",
            ),
            dense_model=self.get(
                "knowledge_dense_model",
                "KNOWLEDGE_DENSE_MODEL",
                "Qwen/Qwen3-Embedding-0.6B",
            ),
            reranker_model=self.get(
                "knowledge_reranker_model",
                "KNOWLEDGE_RERANKER_MODEL",
                "Qwen/Qwen3-Reranker-0.6B",
            ),
            rerank_enabled=_as_bool(
                self.get(
                    "knowledge_rerank_enabled",
                    "KNOWLEDGE_RERANK_ENABLED",
                    "true",
                )
            ),
            retrieval_timeout_seconds=float(
                self.get(
                    "knowledge_retrieval_timeout_seconds",
                    "KNOWLEDGE_RETRIEVAL_TIMEOUT_SECONDS",
                    "8",
                )
            ),
        )

    def agent_model(self, role: str | None = None) -> str:
        if role in {"planner", "synthesizer", "followup"}:
            configured = self.agent_model_override(role)
            if configured:
                return configured
        return self.get("agent_model", "AGENT_LLM_MODEL")

    def agent_model_override(self, role: str) -> str:
        if role not in {"planner", "synthesizer", "followup"}:
            return ""
        return self.get(
            f"agent_{role}_model", f"AGENT_LLM_{role.upper()}_MODEL"
        )

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
    if configured_path:
        path = Path(configured_path)
    else:
        local_app_data = os.getenv("LOCALAPPDATA", "").strip()
        config_root = (
            Path(local_app_data)
            if local_app_data
            else Path.home() / "AppData" / "Local"
        )
        path = config_root / "MarketPilot" / "integration_config.dpapi"
    return EncryptedSecretStore(path, WindowsDpapiProtector())


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


runtime_config = RuntimeConfigStore(_default_secret_store())
