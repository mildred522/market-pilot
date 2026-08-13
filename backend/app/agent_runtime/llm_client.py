from __future__ import annotations

import json
import os
import time
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.services.runtime_config import runtime_config


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class LlmError(RuntimeError):
    """Safe LLM boundary error that never includes credentials."""


class LlmOutputError(LlmError):
    def __init__(
        self,
        message: str,
        *,
        candidate_content: str | None,
        error_code: str,
    ) -> None:
        self.candidate_content = candidate_content
        self.error_code = error_code
        super().__init__(message)


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
        timeout_seconds: float = 75.0,
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
        except (KeyError, IndexError, TypeError) as error:
            raise LlmOutputError(
                "LLM response did not contain message content",
                candidate_content=None,
                error_code="missing_content",
            ) from error
        if not isinstance(content, str):
            raise LlmOutputError(
                "LLM message content was not text",
                candidate_content=None,
                error_code="non_text_content",
            )
        candidate = _safe_candidate_content(content, self._api_key)
        try:
            parsed = json.loads(_strip_code_fence(content))
        except json.JSONDecodeError as error:
            raise LlmOutputError(
                "LLM returned invalid JSON",
                candidate_content=candidate,
                error_code="invalid_json",
            ) from error
        try:
            return response_model.model_validate(parsed)
        except ValidationError as error:
            raise LlmOutputError(
                "LLM output did not match the required schema: "
                + _validation_error_summary(error),
                candidate_content=_candidate_answer(parsed) or candidate,
                error_code="schema_validation",
            ) from error

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
    api_key = runtime_config.get("agent_api_key", "AGENT_LLM_API_KEY")
    model = runtime_config.get("agent_model", "AGENT_LLM_MODEL")
    if not api_key or not model:
        return DisabledLlmClient()
    return OpenAiCompatibleLlmClient(
        api_key=api_key,
        model=model,
        base_url=runtime_config.get(
            "agent_base_url", "AGENT_LLM_BASE_URL", "https://api.openai.com/v1"
        ),
        provider=runtime_config.get(
            "agent_provider", "AGENT_LLM_PROVIDER", "openai-compatible"
        ),
        timeout_seconds=float(os.getenv("AGENT_LLM_TIMEOUT_SECONDS", "75")),
    )


def _strip_code_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return text


def _safe_candidate_content(content: str, api_key: str) -> str | None:
    redacted = content.replace(api_key, "[redacted]").strip()
    return redacted[:4000] or None


def _candidate_answer(parsed: object) -> str | None:
    if isinstance(parsed, dict) and isinstance(parsed.get("answer"), str):
        return parsed["answer"].strip()[:4000] or None
    return None


def _validation_error_summary(error: ValidationError, limit: int = 4) -> str:
    summaries: list[str] = []
    for item in error.errors(include_url=False, include_context=False)[:limit]:
        location = ".".join(str(part) for part in item.get("loc", ())) or "root"
        summaries.append(f"{location}: {item.get('msg', 'invalid value')}")
    remaining = max(0, error.error_count() - len(summaries))
    if remaining:
        summaries.append(f"and {remaining} more validation errors")
    return "; ".join(summaries)
