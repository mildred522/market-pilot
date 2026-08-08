from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BaiduIntegrationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(min_length=8, max_length=200)


class AgentIntegrationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=120)
    base_url: str = Field(default="https://api.openai.com/v1", max_length=500)
    provider: str = Field(default="openai-compatible", min_length=1, max_length=80)

    @field_validator("base_url")
    @classmethod
    def require_http_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("https://", "http://")):
            raise ValueError("base_url must use http or https")
        return normalized


IntegrationName = Literal["baidu", "agent"]
