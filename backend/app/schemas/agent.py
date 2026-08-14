from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.agent_runtime.contracts import CapabilityIntent, CapabilityName

AgentResponseStatus = Literal[
    "completed",
    "clarification",
    "insufficient_data",
    "provider_failure",
    "tool_failure",
]


class AgentAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: StrictInt | None = Field(default=None, gt=0)
    intent: CapabilityIntent
    inputs: dict[str, Any] = Field(default_factory=dict)


class AgentFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["input", "provider", "tool"]
    code: str
    message: str
    retryable: bool = False


class AgentAnalyzeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AgentResponseStatus
    capability: CapabilityName
    intent: CapabilityIntent
    missing_fields: list[str] = Field(default_factory=list)
    result: Any | None = None
    failure: AgentFailure | None = None
