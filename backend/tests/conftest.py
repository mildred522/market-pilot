import importlib

import pytest

from app.agent_runtime import llm_client as llm_client_module
from app.api import dashboard as dashboard_module
from app.external_context import baidu_client as baidu_client_module
from app.services.runtime_config import RuntimeConfigStore


@pytest.fixture(autouse=True)
def isolate_persisted_integration_config(monkeypatch: pytest.MonkeyPatch) -> None:
    test_config = RuntimeConfigStore()
    runtime_config_module = importlib.import_module("app.services.runtime_config")
    monkeypatch.setattr(runtime_config_module, "runtime_config", test_config)
    monkeypatch.setattr(llm_client_module, "runtime_config", test_config)
    monkeypatch.setattr(baidu_client_module, "runtime_config", test_config)
    monkeypatch.setattr(dashboard_module, "runtime_config", test_config)
