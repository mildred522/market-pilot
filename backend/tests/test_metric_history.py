from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import AnalysisResult, Base, Project
from app.agent_runtime.contracts import FollowupStep
from app.agent_runtime.followup import ReportFollowupAgent
from app.memory.history_service import MetricHistoryService


def _result(
    project_id: int, revenue: float, *, stage: str = "operating"
) -> AnalysisResult:
    return AnalysisResult(
        project_id=project_id,
        stage=stage,
        summary="摘要",
        metrics_json={"revenue": {"total_revenue": revenue}},
        evidence_json=[],
        actions_json=[],
        warnings_json=[],
    )


def test_history_reads_same_metric_from_previous_analysis_of_same_project():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="历史对比店", stage="operating")
        other = Project(name="其他店", stage="operating")
        db.add_all([project, other])
        db.flush()
        previous = _result(project.id, 300.0)
        cross_stage = _result(project.id, 8888.0, stage="pre_open")
        current = _result(project.id, 360.0)
        db.add_all([previous, cross_stage, current, _result(other.id, 9999.0)])
        db.flush()

        history = MetricHistoryService(
            db,
            project_id=project.id,
            current_analysis_id=current.id,
            current_metrics=current.metrics_json,
        ).read("metrics.revenue.total_revenue")

        assert history["current_value"] == 360.0
        assert history["previous_value"] == 300.0
        assert history["absolute_change"] == 60.0
        assert history["relative_change"] == 0.2
        assert history["unit"] == "currency"
        assert history["evidence_refs"] == [
            "metrics.revenue.total_revenue",
            f"history.analysis.{previous.id}.metrics.revenue.total_revenue",
        ]


def test_followup_agent_reads_and_cites_metric_history():
    class HistoryClient:
        configured = True
        provider = "fake"
        model = "fake"

        def __init__(self, history_ref: str):
            self.history_ref = history_ref
            self.steps = 0

        def generate_json(self, **_kwargs):
            self.steps += 1
            if self.steps == 1:
                return FollowupStep(
                    action="tool",
                    tool_name="read_metric_history",
                    arguments={"path": "metrics.revenue.total_revenue"},
                )
            return FollowupStep(
                action="answer",
                answer="本期总营收较上期增加 60 元。",
                evidence_refs=[
                    "metrics.revenue.total_revenue",
                    self.history_ref,
                ],
                confidence=0.95,
            )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="历史追问店", stage="operating")
        db.add(project)
        db.flush()
        previous = _result(project.id, 300.0)
        current = _result(project.id, 360.0)
        db.add_all([previous, current])
        db.flush()
        service = MetricHistoryService(
            db,
            project_id=project.id,
            current_analysis_id=current.id,
            current_metrics=current.metrics_json,
        )
        history_ref = f"history.analysis.{previous.id}.metrics.revenue.total_revenue"

        answer = ReportFollowupAgent(HistoryClient(history_ref)).answer(
            question="总营收比上一期变化多少？",
            summary="当前摘要",
            metrics=current.metrics_json,
            evidence=[],
            actions=[],
            risks=[],
            history_service=service,
        )

        assert answer["mode"] == "llm"
        assert answer["evidence_refs"] == [
            "metrics.revenue.total_revenue",
            history_ref,
        ]
        assert answer["tool_calls"][0]["tool"] == "read_metric_history"
        assert answer["tool_calls"][0]["arguments"] == {
            "path": "metrics.revenue.total_revenue"
        }
