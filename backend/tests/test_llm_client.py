import json

import httpx
import pytest

from app.agent_runtime.contracts import AgentPlan
from app.agent_runtime.llm_client import (
    DisabledLlmClient,
    LlmError,
    OpenAiCompatibleLlmClient,
    llm_client_from_environment,
)


def test_openai_compatible_client_validates_structured_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "intent": "operating_diagnosis",
                                    "goal": "find revenue decline",
                                    "tools": [
                                        {
                                            "name": "analyze_revenue",
                                            "reason": "measure revenue",
                                        }
                                    ],
                                    "missing_inputs": [],
                                    "requires_external_api": False,
                                }
                            )
                        }
                    }
                ]
            },
        )

    client = OpenAiCompatibleLlmClient(
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        transport=httpx.MockTransport(handler),
    )

    result = client.generate_json(
        system_prompt="plan",
        user_prompt="question",
        response_model=AgentPlan,
        temperature=0.1,
    )

    assert result.tools[0].name == "analyze_revenue"


def test_openai_compatible_client_rejects_invalid_schema():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"intent": "missing"}'}}]},
        )
    )
    client = OpenAiCompatibleLlmClient(
        api_key="test-key",
        model="test-model",
        transport=transport,
    )

    with pytest.raises(LlmError, match="invalid structured output"):
        client.generate_json(
            system_prompt="plan",
            user_prompt="question",
            response_model=AgentPlan,
            temperature=0.1,
        )


def test_environment_factory_is_disabled_without_credentials(monkeypatch):
    monkeypatch.delenv("AGENT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_LLM_MODEL", raising=False)

    assert isinstance(llm_client_from_environment(), DisabledLlmClient)
