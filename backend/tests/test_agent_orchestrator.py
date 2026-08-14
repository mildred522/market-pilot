from dataclasses import replace
from pathlib import Path

import pandas as pd

from app.agent_runtime.contracts import (
    AgentPlan,
    CompactAgentSynthesis,
    PlannedTool,
    SynthesisFinding,
)
from app.agent_runtime.llm_client import DisabledLlmClient
from app.agent_runtime.orchestrator import OperatingAgentOrchestrator
from app.agent_runtime.tools import OPERATING_TOOLS
from app.services.agent_service import AgentService


SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data"


class FakeLlmClient:
    configured = True
    provider = "fake"
    model = "fake-model"

    def __init__(self, evidence_ref: str = "metrics.revenue.total_revenue") -> None:
        self.evidence_ref = evidence_ref
        self.calls: list[str] = []
        self.user_prompts: list[str] = []

    def generate_json(
        self, *, system_prompt, user_prompt, response_model, temperature
    ):
        self.calls.append(response_model.__name__)
        self.user_prompts.append(user_prompt)
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
        return CompactAgentSynthesis(
            summary="AI 诊断：样本营收需要结合趋势进一步观察。",
            findings=[
                SynthesisFinding(
                    claim="样本期营收已由工具完成核算",
                    evidence_refs=[self.evidence_ref],
                )
            ],
            actions=[
                "连续记录重点时段订单；指标：午市订单数，目标：提升 10%；期限：14 天"
            ],
        )


def _service(client: FakeLlmClient) -> AgentService:
    return AgentService(OperatingAgentOrchestrator(client))


def _analyze(
    service: AgentService,
    *,
    question: str = "分析营收趋势",
    analysis_mode: str = "full",
):
    return service.analyze_operating(
        project_id=1,
        question=question,
        analysis_mode=analysis_mode,
        orders=pd.read_csv(SAMPLE_DIR / "orders.csv"),
        menu=pd.read_csv(SAMPLE_DIR / "menu_items.csv"),
        reviews=pd.read_csv(SAMPLE_DIR / "reviews.csv"),
        cost_assumptions=None,
    )


def test_orchestrator_uses_llm_plan_and_grounded_synthesis():
    client = FakeLlmClient()

    report = _analyze(_service(client))

    assert client.calls == ["AgentPlan", "CompactAgentSynthesis"]
    assert report["summary"].startswith("AI 诊断")
    assert report["agent_trace"]["mode"] == "llm"
    assert report["agent_trace"]["selected_tools"] == [
        "analyze_revenue",
        "analyze_menu_matrix",
        "analyze_review_topics",
        "analyze_time_patterns",
        "analyze_discount_profitability",
    ]
    assert "期限：14 天" in report["actions"][0]
    assert "metrics.revenue.total_revenue" in report["evidence"][0]
    assert '"output_contract"' in client.user_prompts[0]
    assert '"label": "总营收"' in client.user_prompts[0]
    assert '"metric_evidence"' in client.user_prompts[1]
    assert '"metric_definitions"' not in client.user_prompts[1]
    llm_calls = report["agent_trace"]["llm_calls"]
    assert [item["role"] for item in llm_calls] == ["planner", "synthesizer"]
    assert all(item["provider"] == "fake" for item in llm_calls)
    assert "prompt" not in str(llm_calls).lower()
    assert len(report["agent_trace"]["request_id"]) == 36
    assert report["agent_trace"]["initial_plan"]["intent"] == "operating_diagnosis"
    assert report["agent_trace"]["final_plan"]["intent"] == "operating_diagnosis"


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


def test_orchestrator_always_adds_channel_analysis_when_inputs_are_available():
    service = _service(FakeLlmClient())

    report = service.analyze_operating(
        project_id=1,
        question="分析营收趋势",
        orders=pd.read_csv(SAMPLE_DIR / "orders.csv"),
        menu=pd.read_csv(SAMPLE_DIR / "menu_items.csv"),
        reviews=pd.read_csv(SAMPLE_DIR / "reviews.csv"),
        cost_assumptions={
            "delivery_commission_rate": 0.2,
            "delivery_packaging_per_order": 1.5,
        },
    )

    assert "analyze_channel_profitability" in report["agent_trace"]["selected_tools"]
    assert report["metrics"]["channels"]["delivery_revenue_share"] == 0.3333


def test_orchestrator_continues_when_optional_tool_fails(monkeypatch):
    def fail(_context):
        raise RuntimeError("sensitive provider response")

    monkeypatch.setitem(
        OPERATING_TOOLS,
        "analyze_time_patterns",
        replace(OPERATING_TOOLS["analyze_time_patterns"], runner=fail),
    )

    report = _analyze(_service(FakeLlmClient()))

    assert report["agent_trace"]["status"] == "degraded"
    assert "time_patterns" not in report["metrics"]
    failed = next(
        item
        for item in report["agent_trace"]["tool_executions"]
        if item["tool_name"] == "analyze_time_patterns"
    )
    assert failed["status"] == "failed"
    assert failed["error_code"] == "tool_execution_failed"
    assert "sensitive provider response" not in str(report["agent_trace"])
    assert any("time_patterns" in warning for warning in report["warnings"])
    assert report["summary"].startswith("AI 诊断")


def test_orchestrator_stops_before_synthesis_when_required_tool_fails(monkeypatch):
    def fail(_context):
        raise ValueError("secret database exception")

    monkeypatch.setitem(
        OPERATING_TOOLS,
        "analyze_revenue",
        replace(OPERATING_TOOLS["analyze_revenue"], runner=fail),
    )
    client = FakeLlmClient()

    report = _analyze(_service(client))

    assert client.calls == ["AgentPlan"]
    assert report["agent_trace"]["status"] == "failed"
    assert len(report["agent_trace"]["tool_executions"]) == 1
    assert report["agent_trace"]["tool_executions"][0]["error_code"] == "tool_input_invalid"
    assert "数据不足" in report["summary"]
    assert "revenue" not in report["metrics"]
    assert "secret database exception" not in str(report)


def test_orchestrator_focused_mode_executes_only_the_planned_tool():
    report = _analyze(
        _service(FakeLlmClient("metrics.time_patterns.peak_daypart")),
        question="营收最高的时段是什么",
        analysis_mode="focused",
    )

    assert report["agent_trace"]["analysis_mode"] == "focused"
    assert report["agent_trace"]["selected_tools"] == ["analyze_time_patterns"]
    assert "time_patterns" in report["metrics"]
    assert "revenue" not in report["metrics"]


def test_orchestrator_focused_deterministic_mode_synthesizes_partial_results():
    report = _analyze(
        AgentService(OperatingAgentOrchestrator(DisabledLlmClient())),
        question="只看中差评情况",
        analysis_mode="focused",
    )

    assert report["agent_trace"]["selected_tools"] == ["analyze_review_topics"]
    assert report["agent_trace"]["status"] == "completed"
    assert set(report["metrics"]) >= {
        "reviews",
        "_agent",
        "_agent_plan",
        "_data_resources",
    }
    assert "revenue" not in report["metrics"]
    assert report["summary"]


def test_orchestrator_focused_tool_failure_is_required(monkeypatch):
    def fail(_context):
        raise ValueError("invalid business input")

    monkeypatch.setitem(
        OPERATING_TOOLS,
        "analyze_time_patterns",
        replace(OPERATING_TOOLS["analyze_time_patterns"], runner=fail),
    )
    client = FakeLlmClient("metrics.time_patterns.peak_daypart")

    report = _analyze(
        _service(client),
        question="营收最高的时段是什么",
        analysis_mode="focused",
    )

    assert client.calls == ["AgentPlan"]
    assert report["agent_trace"]["status"] == "failed"
    assert report["agent_trace"]["selected_tools"] == ["analyze_time_patterns"]


def test_orchestrator_replans_once_after_recoverable_required_failure(monkeypatch):
    attempts = 0
    original = OPERATING_TOOLS["analyze_time_patterns"].runner

    def fail_once(context):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary worker failure")
        return original(context)

    monkeypatch.setitem(
        OPERATING_TOOLS,
        "analyze_time_patterns",
        replace(OPERATING_TOOLS["analyze_time_patterns"], runner=fail_once),
    )
    client = FakeLlmClient("metrics.time_patterns.peak_daypart")

    report = _analyze(
        _service(client),
        question="营收最高的时段是什么",
        analysis_mode="focused",
    )

    assert client.calls == ["AgentPlan", "AgentPlan", "CompactAgentSynthesis"]
    assert attempts == 2
    assert report["agent_trace"]["replan_count"] == 1
    assert report["agent_trace"]["replan"] == {
        "trigger": "recoverable_tool_failure",
        "initial_tools": ["analyze_time_patterns"],
        "failed_tools": ["analyze_time_patterns"],
        "revised_tools": ["analyze_time_patterns"],
        "outcome": "recovered",
    }
    assert [item["status"] for item in report["agent_trace"]["tool_executions"]] == [
        "failed",
        "completed",
    ]
    assert report["agent_trace"]["status"] == "degraded"


def test_orchestrator_never_replans_more_than_once(monkeypatch):
    attempts = 0

    def always_fail(_context):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("temporary worker failure")

    monkeypatch.setitem(
        OPERATING_TOOLS,
        "analyze_time_patterns",
        replace(OPERATING_TOOLS["analyze_time_patterns"], runner=always_fail),
    )
    client = FakeLlmClient("metrics.time_patterns.peak_daypart")

    report = _analyze(
        _service(client),
        question="营收最高的时段是什么",
        analysis_mode="focused",
    )

    assert client.calls == ["AgentPlan", "AgentPlan"]
    assert attempts == 2
    assert report["agent_trace"]["replan_count"] == 1
    assert report["agent_trace"]["status"] == "failed"
    assert report["agent_trace"]["replan"]["outcome"] == "failed"
