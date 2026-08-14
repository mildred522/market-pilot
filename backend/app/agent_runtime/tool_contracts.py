from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent_runtime.metric_registry import definition_for


ToolExecutionStatus = Literal["completed", "degraded", "failed"]


class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1, max_length=80)
    output_section: str = Field(min_length=1, max_length=80)
    status: ToolExecutionStatus
    data: dict[str, Any] | None = None
    evidence: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, max_length=8)
    error_code: str | None = Field(default=None, max_length=80)
    duration_ms: int = Field(ge=0)
    from_cache: bool = False

    @model_validator(mode="after")
    def validate_status_payload(self) -> ToolExecutionResult:
        if self.status == "failed":
            if self.data is not None or self.error_code is None:
                raise ValueError("failed tool results require an error code and no data")
        elif self.data is None:
            raise ValueError("completed or degraded tool results require data")
        return self


class ToolExecutionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executions: list[ToolExecutionResult]
    stopped_early: bool = False

    @property
    def successful_data(self) -> dict[str, Any]:
        return {
            item.output_section: item.data
            for item in self.executions
            if item.status in {"completed", "degraded"} and item.data is not None
        }

    @property
    def status(self) -> ToolExecutionStatus:
        if self.stopped_early:
            return "failed"
        if any(item.status != "completed" for item in self.executions):
            return "degraded"
        return "completed"


def validate_tool_output(
    *, tool_name: str, output_section: str, data: object
) -> dict[str, Any]:
    if not isinstance(data, dict) or not data:
        raise ValueError("tool output must be a non-empty object")

    unknown_paths: list[str] = []
    wrong_sources: list[str] = []
    for path in _public_paths(data, f"metrics.{output_section}"):
        definition = definition_for(path)
        if definition is None:
            unknown_paths.append(path)
        elif definition.source_tool != tool_name:
            wrong_sources.append(path)
    if unknown_paths:
        raise ValueError(
            f"tool output has no metric contract: {', '.join(unknown_paths)}"
        )
    if wrong_sources:
        raise ValueError(
            f"tool output belongs to a different source tool: {', '.join(wrong_sources)}"
        )
    return data


def evidence_references(output_section: str, data: dict[str, Any]) -> list[str]:
    return _public_paths(data, f"metrics.{output_section}")


def _public_paths(value: Any, path: str) -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            if not str(key).startswith("_"):
                paths.extend(_public_paths(child, f"{path}.{key}"))
        return paths
    return [path]
