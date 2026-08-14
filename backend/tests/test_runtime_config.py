import os

import pytest

from app.agent_runtime import llm_client as llm_client_module
from app.agent_runtime.llm_client import OpenAiCompatibleLlmClient, llm_client_from_environment
from app.services.runtime_config import RuntimeConfigStore
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
