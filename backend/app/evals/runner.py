from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from app.evals.contracts import (
    AgentEvalCase,
    AgentEvalCaseExecution,
    AgentEvalReport,
    AgentEvalResult,
)
from app.evals.scorers import aggregate_scores, score_case


class AgentEvalAdapter(Protocol):
    def execute(self, case: AgentEvalCase) -> AgentEvalResult: ...


def load_cases(path: Path) -> list[AgentEvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("evaluation case file must contain a JSON array")
    return [AgentEvalCase.model_validate(item) for item in payload]


def run_cases(
    cases: list[AgentEvalCase], adapter: AgentEvalAdapter
) -> AgentEvalReport:
    identifiers = [case.case_id for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate evaluation case id")

    executions: list[AgentEvalCaseExecution] = []
    for case in cases:
        result = adapter.execute(case)
        executions.append(
            AgentEvalCaseExecution(
                case=case,
                result=result,
                score=score_case(case, result),
            )
        )
    return AgentEvalReport(
        cases=executions,
        summary=aggregate_scores([item.score for item in executions]),
    )
