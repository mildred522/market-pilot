from __future__ import annotations

import json
import os
import time
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class LlmError(RuntimeError):
    """Safe LLM boundary error that never includes credentials."""


class LlmClient(Protocol):
    @property
    def configured(self) -> bool: ...

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str | None: ...

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModel],
        temperature: float,
    ) -> ResponseModel: ...


class DisabledLlmClient:
    configured = False
    provider = "disabled"
    model = None

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModel],
        temperature: float,
    ) -> ResponseModel:
        raise LlmError("LLM is not configured")


class OpenAiCompatibleLlmClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        provider: str = "openai-compatible",
        timeout_seconds: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._provider = provider
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._model)

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModel],
        temperature: float,
    ) -> ResponseModel:
        schema = response_model.model_json_schema()
        payload = {
            "model": self._model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": f"{system_prompt}\nReturn JSON matching this schema:\n{json.dumps(schema, ensure_ascii=False)}",
                },
                {"role": "user", "content": user_prompt},
            ],
        }
        data = self._post_with_retry(payload)
        try:
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(_strip_code_fence(content))
            return response_model.model_validate(parsed)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as error:
            raise LlmError("LLM returned invalid structured output") from error

    def _post_with_retry(self, payload: dict[str, object]) -> dict[str, object]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        for attempt in range(2):
            try:
                with httpx.Client(
                    timeout=self._timeout_seconds,
                    transport=self._transport,
                ) as client:
                    response = client.post(
                        f"{self._base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 0:
                        time.sleep(0.25)
                        continue
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict):
                    raise LlmError("LLM response was not an object")
                return result
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                if attempt == 0:
                    time.sleep(0.25)
                    continue
                raise LlmError("LLM request timed out or failed") from error
            except httpx.HTTPStatusError as error:
                raise LlmError(f"LLM request failed with HTTP {error.response.status_code}") from error
            except (ValueError, json.JSONDecodeError) as error:
                raise LlmError("LLM response could not be decoded") from error
        raise LlmError("LLM request failed")


def llm_client_from_environment() -> LlmClient:
    api_key = os.getenv("AGENT_LLM_API_KEY", "").strip()
    model = os.getenv("AGENT_LLM_MODEL", "").strip()
    if not api_key or not model:
        return DisabledLlmClient()
    return OpenAiCompatibleLlmClient(
        api_key=api_key,
        model=model,
        base_url=os.getenv("AGENT_LLM_BASE_URL", "https://api.openai.com/v1").strip(),
        provider=os.getenv("AGENT_LLM_PROVIDER", "openai-compatible").strip(),
        timeout_seconds=float(os.getenv("AGENT_LLM_TIMEOUT_SECONDS", "20")),
    )


def _strip_code_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return text
