import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent_runtime.contracts import (
    FollowupAnswerSections,
    FollowupDataClaim,
    FollowupEvidenceRequest,
    FollowupStep,
)
from app.agent_runtime.followup import ReportFollowupAgent
from app.agent_runtime.followup_evidence import (
    CapabilityEvidenceResult,
    EvidenceMaterial,
    apply_followup_evidence_policy,
)
from app.db.models import AnalysisResult, Base, Project
from app.memory.history_service import MetricHistoryService


class HistoryPlanningClient:
    configured = True
    provider = "fake"
    model = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def generate_json(self, *, user_prompt, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return FollowupStep(
                action="retrieve",
                evidence_requests=[
                    FollowupEvidenceRequest(
                        capability="metric_history",
                        purpose="比较本期和上一期总营收",
                        requirement="required",
                        success_condition="返回同口径的两期总营收和变化额",
                    )
                ],
            )
        prompt = json.loads(user_prompt)
        fact = next(
            item
            for item in prompt["evidence_pack"]["facts"]
            if item["canonical_ref"].startswith("history.comparison.")
        )
        return FollowupStep(
            action="answer",
            sections=FollowupAnswerSections(
                data_findings=[
                    FollowupDataClaim(
                        text="本期总营收较上期增加 60 元。",
                        evidence_ids=[fact["id"]],
                    )
                ]
            ),
            confidence=0.96,
        )


class ScriptedPlanningClient:
    configured = True
    provider = "fake"
    model = "fake"

    def __init__(self, first_capability: str, second_capability: str | None = None):
        self.first_capability = first_capability
        self.second_capability = second_capability
        self.calls = 0

    def generate_json(self, *, user_prompt, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return _retrieve_step(self.first_capability)
        prompt = json.loads(user_prompt)
        failed = any(
            item.get("status") == "failed"
            for item in prompt.get("observations", [])
            if item.get("action") == "retrieve_evidence"
        )
        if self.calls == 2 and failed and self.second_capability:
            return _retrieve_step(self.second_capability)
        external_fact = next(
            (
                item
                for item in prompt["evidence_pack"]["facts"]
                if item["source"] == "external_context"
            ),
            None,
        )
        if external_fact:
            return FollowupStep(
                action="answer",
                sections=FollowupAnswerSections(
                    data_findings=[
                        FollowupDataClaim(
                            text="已获得带来源的外部经营背景。",
                            evidence_ids=[external_fact["id"]],
                        )
                    ]
                ),
                confidence=0.9,
            )
        return FollowupStep(
            action="answer",
            sections=FollowupAnswerSections(
                general_advice=["可以先用门店内的小规模试验验证方向。"],
                missing_information=["当前没有可用的外部客观证据。"],
            ),
            confidence=0.65,
        )


class FakeEvidenceProvider:
    def __init__(self, outcomes: dict[str, CapabilityEvidenceResult]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []
        self.contexts = []

    def available_capabilities(self, _profile):
        return set(self.outcomes)

    def retrieve(self, capability, context):
        self.calls.append(capability)
        self.contexts.append(context)
        return self.outcomes[capability]


def test_followup_history_plan_compiles_metric_and_expands_evidence_pack():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="历史计划店", stage="operating")
        db.add(project)
        db.flush()
        previous = _analysis(project.id, 300)
        current = _analysis(project.id, 360)
        db.add_all([previous, current])
        db.flush()
        history = MetricHistoryService(
            db,
            project_id=project.id,
            current_analysis_id=current.id,
            current_metrics=current.metrics_json,
        )

        result = ReportFollowupAgent(HistoryPlanningClient()).answer(
            question="总营收和上期相比变化多少？",
            summary="当前报告",
            metrics=current.metrics_json,
            evidence=[],
            actions=[],
            risks=[],
            history_service=history,
        )

    assert result["quality"] == "complete"
    assert result["steps"] == 2
    assert result["tool_calls"] == [
        {
            "tool": "metric_history",
            "arguments": {"purpose": "比较本期和上一期总营收"},
        }
    ]
    assert result["evidence_refs"] == [
        "history.comparison.metrics.revenue.total_revenue"
    ]
    assert result["agent_trace"]["replan_count"] == 0


def test_followup_replans_once_after_required_evidence_failure():
    provider = FakeEvidenceProvider(
        {
            "external_industry_context": CapabilityEvidenceResult(
                capability="external_industry_context",
                status="failed",
                error_code="provider_timeout",
            ),
            "location_competitors": CapabilityEvidenceResult(
                capability="location_competitors",
                status="completed",
                facts=(
                    EvidenceMaterial(
                        canonical_ref="external.location_snapshot.7.metrics.competitor_count",
                        source="external_context",
                        label="周边竞品数",
                        value=8,
                    ),
                ),
            ),
        }
    )
    client = ScriptedPlanningClient(
        "external_industry_context", "location_competitors"
    )

    result = ReportFollowupAgent(client).answer(
        question="结合成都趋势和附近竞品分析",
        summary="当前报告",
        metrics={"_project_profile": {"city": "chengdu", "category": "milk-tea"}},
        evidence=[],
        actions=[],
        risks=[],
        evidence_provider=provider,
    )

    assert result["quality"] == "complete"
    assert result["steps"] == 3
    assert provider.calls == [
        "external_industry_context",
        "location_competitors",
    ]
    assert provider.contexts[0].question == "结合成都趋势和附近竞品分析"
    assert provider.contexts[0].project_profile == {
        "city": "chengdu",
        "category": "milk-tea",
    }
    assert provider.contexts[0].success_condition == "返回带来源和时间范围的事实"
    assert result["agent_trace"]["replan_count"] == 1
    assert result["agent_trace"]["evidence_events"] == [
        {
            "action": "retrieve_evidence",
            "capability": "external_industry_context",
            "requirement": "required",
            "status": "failed",
            "evidence_refs": [],
            "error": {"code": "provider_timeout", "message": None},
        },
        {
            "action": "retrieve_evidence",
            "capability": "location_competitors",
            "requirement": "required",
            "status": "completed",
            "evidence_refs": [
                "external.location_snapshot.7.metrics.competitor_count"
            ],
            "error": None,
        },
    ]
    assert [item["role"] for item in result["llm_calls"]] == [
        "followup",
        "replanner",
        "followup",
    ]


def test_external_evidence_is_not_labelled_as_store_data():
    provider = FakeEvidenceProvider(
        {
            "external_industry_context": CapabilityEvidenceResult(
                capability="external_industry_context",
                status="completed",
                facts=(
                    EvidenceMaterial(
                        canonical_ref="external.knowledge.source.1.version.1.chunk.kv1-c0001",
                        source="external_context",
                        label="行业趋势",
                        value="持续上新有助于保持产品差异化。",
                    ),
                ),
            )
        }
    )

    result = ReportFollowupAgent(
        ScriptedPlanningClient("external_industry_context")
    ).answer(
        question="结合行业趋势给出建议",
        summary="当前报告",
        metrics={"_project_profile": {"category": "新茶饮"}},
        evidence=[],
        actions=[],
        risks=[],
        evidence_provider=provider,
    )

    assert "外部行业证据" in result["answer"]
    assert "基于门店数据" not in result["answer"]
    assert result["sections"]["data_findings"][0]["scope"] == "external"


def test_optional_external_failure_does_not_trigger_replan():
    request = FollowupEvidenceRequest(
        capability="external_industry_context",
        purpose="补充行业背景",
        requirement="optional",
        success_condition="返回带来源的行业数据",
    )
    decision = apply_followup_evidence_policy(
        [request],
        question="根据当前营收给一些建议",
        history_available=False,
        provider_capabilities={"external_industry_context"},
        attempted_capabilities=set(),
    )

    assert decision.approved == ()
    assert decision.rejected[0]["error_code"] == "optional_retrieval_not_justified"


def test_industry_context_cannot_substitute_for_local_competitor_evidence():
    request = FollowupEvidenceRequest(
        capability="external_industry_context",
        purpose="查找附近竞品",
        requirement="required",
        success_condition="返回三公里内的竞品",
    )

    decision = apply_followup_evidence_policy(
        [request],
        question="附近三公里有哪些直接竞品？",
        history_available=False,
        provider_capabilities={"external_industry_context"},
        attempted_capabilities=set(),
    )

    assert decision.approved == ()
    assert decision.rejected[0]["error_code"] == "capability_not_relevant"


def _retrieve_step(capability: str) -> FollowupStep:
    return FollowupStep(
        action="retrieve",
        evidence_requests=[
            FollowupEvidenceRequest(
                capability=capability,
                purpose=f"获取{capability}证据",
                requirement="required",
                success_condition="返回带来源和时间范围的事实",
            )
        ],
    )


def _analysis(project_id: int, revenue: float) -> AnalysisResult:
    return AnalysisResult(
        project_id=project_id,
        stage="operating",
        summary="摘要",
        metrics_json={"revenue": {"total_revenue": revenue}},
        evidence_json=[],
        actions_json=[],
        warnings_json=[],
    )
