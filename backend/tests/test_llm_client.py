import json

import httpx
import pytest

from app.agent_runtime import llm_client as llm_client_module
from app.agent_runtime.contracts import AgentPlan, FollowupStep
from app.agent_runtime.llm_client import (
    DisabledLlmClient,
    LlmError,
    LlmOutputError,
    OpenAiCompatibleLlmClient,
    llm_client_from_environment,
)
from app.services.runtime_config import RuntimeConfigStore


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

    with pytest.raises(LlmOutputError, match="required schema") as captured:
        client.generate_json(
            system_prompt="plan",
            user_prompt="question",
            response_model=AgentPlan,
            temperature=0.1,
        )
    assert captured.value.error_code == "schema_validation"
    assert captured.value.candidate_content == '{"intent": "missing"}'


def test_openai_compatible_client_applies_schema_defaults_to_null_containers():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "action": "retrieve",
                                    "arguments": None,
                                    "evidence_refs": None,
                                    "evidence_requests": [
                                        {
                                            "capability": "external_industry_context",
                                            "purpose": "read market context",
                                            "requirement": "required",
                                            "success_condition": "return sourced facts",
                                        }
                                    ],
                                }
                            )
                        }
                    }
                ]
            },
        )
    )
    client = OpenAiCompatibleLlmClient(
        api_key="test-key",
        model="test-model",
        transport=transport,
    )

    result = client.generate_json(
        system_prompt="follow up",
        user_prompt="question",
        response_model=FollowupStep,
        temperature=0.1,
    )

    assert result.arguments.model_dump(exclude_none=True) == {}
    assert result.evidence_refs == []
    assert result.evidence_requests[0].capability == "external_industry_context"


def test_openai_compatible_client_preserves_and_redacts_invalid_json_candidate():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": "candidate test-key answer"}}]},
        )
    )
    client = OpenAiCompatibleLlmClient(
        api_key="test-key",
        model="test-model",
        transport=transport,
    )

    with pytest.raises(LlmOutputError, match="invalid JSON") as captured:
        client.generate_json(
            system_prompt="plan",
            user_prompt="question",
            response_model=AgentPlan,
            temperature=0.1,
        )

    assert captured.value.error_code == "invalid_json"
    assert captured.value.candidate_content == "candidate [redacted] answer"


def test_environment_factory_is_disabled_without_credentials(monkeypatch):
    monkeypatch.delenv("AGENT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_LLM_MODEL", raising=False)
    monkeypatch.setattr(llm_client_module, "runtime_config", RuntimeConfigStore())

    assert isinstance(llm_client_from_environment(), DisabledLlmClient)


def test_generation_returns_safe_provider_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-request-id": "req-provider-123"},
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "intent": "operating_diagnosis",
                                    "goal": "inspect revenue",
                                    "tools": [],
                                    "missing_inputs": [],
                                    "requires_external_api": False,
                                }
                            )
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "total_tokens": 150,
                },
            },
        )

    client = OpenAiCompatibleLlmClient(
        api_key="secret-key",
        model="planner-model",
        provider="test-provider",
        transport=httpx.MockTransport(handler),
    )

    generation = client.generate_json_with_metadata(
        role="planner",
        system_prompt="private system prompt",
        user_prompt="private user prompt",
        response_model=AgentPlan,
        temperature=0.1,
    )

    assert generation.output.intent == "operating_diagnosis"
    assert generation.metadata.model_dump() == {
        "role": "planner",
        "provider": "test-provider",
        "model": "planner-model",
        "response_format": "json_object",
        "input_tokens": 120,
        "output_tokens": 30,
        "total_tokens": 150,
        "duration_ms": generation.metadata.duration_ms,
        "retry_count": 0,
        "provider_request_id": "req-provider-123",
        "status": "completed",
        "error_code": None,
    }
    assert generation.metadata.duration_ms >= 0
    serialized = str(generation.metadata.model_dump()).lower()
    assert "prompt" not in serialized
    assert "secret-key" not in serialized


def test_generation_metadata_counts_provider_retry():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "temporarily unavailable"})
        return httpx.Response(
            200,
            json={
                "id": "body-request-id",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "intent": "operating_diagnosis",
                                    "goal": "inspect revenue",
                                    "tools": [],
                                    "missing_inputs": [],
                                    "requires_external_api": False,
                                }
                            )
                        }
                    }
                ],
            },
        )

    client = OpenAiCompatibleLlmClient(
        api_key="secret-key",
        model="planner-model",
        transport=httpx.MockTransport(handler),
    )

    generation = client.generate_json_with_metadata(
        role="planner",
        system_prompt="plan",
        user_prompt="question",
        response_model=AgentPlan,
        temperature=0.1,
    )

    assert attempts == 2
    assert generation.metadata.retry_count == 1
    assert generation.metadata.provider_request_id == "body-request-id"


def test_failed_generation_exposes_safe_failure_metadata():
    client = OpenAiCompatibleLlmClient(
        api_key="secret-key",
        model="planner-model",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, json={"error": "private detail"})
        ),
    )

    with pytest.raises(LlmError) as captured:
        client.generate_json_with_metadata(
            role="planner",
            system_prompt="private system prompt",
            user_prompt="private user prompt",
            response_model=AgentPlan,
            temperature=0.1,
        )

    metadata = captured.value.metadata
    assert metadata is not None
    assert metadata.status == "failed"
    assert metadata.retry_count == 1
    assert metadata.error_code == "model_request_failed"
    assert "private" not in str(metadata.model_dump()).lower()
