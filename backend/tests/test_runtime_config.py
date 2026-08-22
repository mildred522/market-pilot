import os

import pytest

from app.agent_runtime import llm_client as llm_client_module
from app.agent_runtime.llm_client import OpenAiCompatibleLlmClient, llm_client_from_environment
from app.services.runtime_config import RuntimeConfigStore, _default_secret_store
from app.services.secret_store import EncryptedSecretStore, WindowsDpapiProtector


class ReverseProtector:
    def protect(self, value: bytes) -> bytes:
        return value[::-1]

    def unprotect(self, value: bytes) -> bytes:
        return value[::-1]


def test_integration_config_survives_store_recreation_without_plaintext(tmp_path):
    config_path = tmp_path / "integration-config.bin"
    secrets = EncryptedSecretStore(config_path, ReverseProtector())
    first = RuntimeConfigStore(secrets)

    first.set_baidu_key("baidu-secret-value")
    first.set_agent(
        api_key="agent-secret-value",
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        provider="deepseek",
    )

    stored_bytes = config_path.read_bytes()
    assert b"baidu-secret-value" not in stored_bytes
    assert b"agent-secret-value" not in stored_bytes

    restored = RuntimeConfigStore(
        EncryptedSecretStore(config_path, ReverseProtector())
    )
    assert restored.get("baidu_api_key", "UNUSED") == "baidu-secret-value"
    assert restored.get("agent_api_key", "UNUSED") == "agent-secret-value"
    assert restored.status()["agent"]["source"] == "saved"
    assert restored.status()["agent"]["model"] == "deepseek-chat"

    restored.clear("agent")
    reloaded = RuntimeConfigStore(
        EncryptedSecretStore(config_path, ReverseProtector())
    )
    assert reloaded.status()["agent"]["configured"] is False
    assert reloaded.status()["baidu"]["configured"] is True


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI only")
def test_windows_dpapi_round_trip_is_user_scoped_encryption():
    protector = WindowsDpapiProtector()
    plaintext = b"market-pilot-test-secret"

    encrypted = protector.protect(plaintext)

    assert encrypted != plaintext
    assert plaintext not in encrypted
    assert protector.unprotect(encrypted) == plaintext


@pytest.mark.skipif(os.name != "nt", reason="Windows config path only")
def test_default_secret_store_uses_stable_user_config_path(monkeypatch, tmp_path):
    monkeypatch.delenv("MARKET_PILOT_CONFIG_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    store = _default_secret_store()

    assert store is not None
    assert store.path == tmp_path / "MarketPilot" / "integration_config.dpapi"


@pytest.mark.skipif(os.name != "nt", reason="Windows config path only")
def test_secret_store_path_can_be_overridden(monkeypatch, tmp_path):
    configured_path = tmp_path / "custom.dpapi"
    monkeypatch.setenv("MARKET_PILOT_CONFIG_PATH", str(configured_path))

    store = _default_secret_store()

    assert store is not None
    assert store.path == configured_path


def test_agent_models_can_be_configured_by_role_with_base_fallback(monkeypatch):
    config = RuntimeConfigStore()
    config.set_agent(
        api_key="agent-secret-value",
        model="base-model",
        planner_model="small-planner",
        synthesizer_model="quality-synthesizer",
        followup_model="",
        base_url="https://api.example.test/v1",
        provider="test-provider",
    )
    monkeypatch.setattr(llm_client_module, "runtime_config", config)

    planner = llm_client_from_environment("planner")
    synthesizer = llm_client_from_environment("synthesizer")
    followup = llm_client_from_environment("followup")

    assert isinstance(planner, OpenAiCompatibleLlmClient)
    assert planner.model == "small-planner"
    assert synthesizer.model == "quality-synthesizer"
    assert followup.model == "base-model"
    assert config.status()["agent"]["role_models"] == {
        "planner": "small-planner",
        "synthesizer": "quality-synthesizer",
        "followup": None,
    }
    assert config.status()["agent"]["effective_role_models"] == {
        "planner": "small-planner",
        "synthesizer": "quality-synthesizer",
        "followup": "base-model",
    }


def test_knowledge_rag_is_disabled_by_default_and_reads_environment(monkeypatch):
    for name in (
        "KNOWLEDGE_RAG_ENABLED",
        "QDRANT_URL",
        "QDRANT_COLLECTION",
        "KNOWLEDGE_RERANK_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    config = RuntimeConfigStore()

    assert config.knowledge_rag_settings().enabled is False
    assert config.status()["knowledge_rag"]["configured"] is False

    monkeypatch.setenv("KNOWLEDGE_RAG_ENABLED", "true")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant.test:6333")
    monkeypatch.setenv("QDRANT_COLLECTION", "knowledge_test_v2")
    monkeypatch.setenv("KNOWLEDGE_RERANK_ENABLED", "false")

    settings = config.knowledge_rag_settings()
    assert settings.enabled is True
    assert settings.configured is True
    assert settings.collection == "knowledge_test_v2"
    assert settings.rerank_enabled is False
