from pathlib import Path

import pandas as pd

from app.agent_runtime.contracts import (
    AgentAction,
    AgentFinding,
    AgentPlan,
    AgentSynthesis,
    PlannedTool,
)
from app.agent_runtime.orchestrator import OperatingAgentOrchestrator
from app.services.agent_service import AgentService


SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data"


class FakeLlmClient:
    configured = True
    provider = "fake"
    model = "fake-model"

    def __init__(self, evidence_ref: str = "metrics.revenue.total_revenue") -> None:
        self.evidence_ref = evidence_ref
        self.calls: list[str] = []

    def generate_json(
        self, *, system_prompt, user_prompt, response_model, temperature
    ):
        self.calls.append(response_model.__name__)
        if response_model is AgentPlan:
            return AgentPlan(
                intent="operating_diagnosis",
                goal="explain the revenue trend",
                tools=[
                    PlannedTool(
                        name="analyze_time_patterns",
                        reason="measure trend and daypart concentration",
                    )
                ],
            )
        return AgentSynthesis(
            summary="AI 诊断：样本营收需要结合趋势进一步观察。",
            findings=[
                AgentFinding(
                    claim="样本期营收已由工具完成核算",
                    kind="observed",
                    evidence_refs=[self.evidence_ref],
                    confidence=0.95,
                )
            ],
            actions=[
                AgentAction(
                    action="连续记录重点时段订单",
                    metric="午市订单数",
                    target="提升 10%",
                    deadline_days=14,
                )
            ],
        )


def _service(client: FakeLlmClient) -> AgentService:
    return AgentService(OperatingAgentOrchestrator(client))


def _analyze(service: AgentService):
    return service.analyze_operating(
        project_id=1,
        question="分析营收趋势",
        orders=pd.read_csv(SAMPLE_DIR / "orders.csv"),
        menu=pd.read_csv(SAMPLE_DIR / "menu_items.csv"),
        reviews=pd.read_csv(SAMPLE_DIR / "reviews.csv"),
        cost_assumptions=None,
    )


def test_orchestrator_uses_llm_plan_and_grounded_synthesis():
    client = FakeLlmClient()

    report = _analyze(_service(client))

    assert client.calls == ["AgentPlan", "AgentSynthesis"]
    assert report["summary"].startswith("AI 诊断")
    assert report["agent_trace"]["mode"] == "llm"
    assert report["agent_trace"]["selected_tools"] == [
        "analyze_revenue",
        "analyze_menu_matrix",
        "analyze_review_topics",
        "analyze_time_patterns",
    ]
    assert "期限：14 天" in report["actions"][0]
    assert "metrics.revenue.total_revenue" in report["evidence"][0]


def test_orchestrator_falls_back_when_llm_cites_unknown_metric():
    report = _analyze(
        _service(FakeLlmClient("metrics.revenue.not_a_real_metric"))
    )

    assert report["agent_trace"]["mode"] == "hybrid"
    assert report["agent_trace"]["planning_used_llm"] is True
    assert report["agent_trace"]["synthesis_used_llm"] is False
    assert any(
        "unknown evidence reference" in reason
        for reason in report["agent_trace"]["fallback_reasons"]
    )
    assert "当前样本期营收" in report["summary"]
