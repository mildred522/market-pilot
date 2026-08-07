from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    project_id: int
    question: str
    stage: str
    intent: str = ""
    plan: list[str] = field(default_factory=list)
    tool_results: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    evidence: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
