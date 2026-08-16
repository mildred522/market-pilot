from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.agent_runtime.contracts import RevisionLessonCandidate, RevisionPlan
from app.agent_runtime.revision import create_revision_plan
from app.db.models import (
    AnalysisResult,
    Base,
    Project,
)
from app.main import app
from app.memory.repository import ConversationRepository
from app.memory.revision_repository import (
    AnswerVersionRepository,
    RevisionLessonRepository,
)


class RevisionClient:
    configured = True
    provider = "fake"
    model = "fake"

    def generate_json(self, **_kwargs):
        return RevisionPlan(
            revision_type="rewrite_only",
            objective="把回答缩短并先给结论",
            lessons=[
                RevisionLessonCandidate(
                    type="presentation_preference",
                    rule={"answer_order": "conclusion_first", "length": "short"},
                )
            ],
        )


def test_revision_planner_extracts_only_structured_lesson():
    plan, metadata = create_revision_plan(
        client=RevisionClient(),
        original_question="当前最优先处理什么？",
        prior_answer={"answer": "先处理差评。"},
        feedback="以后都先给结论，回答简短一点。",
    )

    assert plan.revision_type == "rewrite_only"
    assert plan.lessons[0].rule == {
        "answer_order": "conclusion_first",
        "length": "short",
    }
    assert metadata[0].role == "revision_planner"


def test_version_repository_preserves_parent_and_public_answer_fields():
    with _session() as db:
        project, analysis, conversation = _conversation(db)
        versions = AnswerVersionRepository(db)
        root = versions.create(
            analysis_id=analysis.id,
            conversation_id=conversation.id,
            parent_version_id=None,
            original_question="怎么改善经营？",
            user_feedback=None,
            revision_type="initial",
            plan={"revision_type": "initial"},
            answer={
                "answer": "先处理差评。",
                "sections": {"general_advice": ["逐条复盘差评。"]},
                "evidence_refs": ["metrics.reviews.negative_review_count"],
                "quality": "complete",
                "mode": "llm",
                "steps": 1,
                "tool_calls": [],
                "failure_detail": {"candidate": "must-not-persist"},
            },
        )
        child = versions.create(
            analysis_id=analysis.id,
            conversation_id=conversation.id,
            parent_version_id=root.id,
            original_question=root.original_question,
            user_feedback="简短一点",
            revision_type="rewrite_only",
            plan={"revision_type": "rewrite_only"},
            answer={"answer": "先处理差评。", "mode": "llm", "steps": 1},
        )

        assert child.parent_version_id == root.id
        assert [item.id for item in versions.list_for_analysis(analysis.id)] == [
            root.id,
            child.id,
        ]
        assert "must-not-persist" not in str(root.__dict__)
        assert project.id > 0


def test_conflicting_lessons_are_explicitly_superseded():
    with _session() as db:
        project, analysis, conversation = _conversation(db)
        version = AnswerVersionRepository(db).create(
            analysis_id=analysis.id,
            conversation_id=conversation.id,
            parent_version_id=None,
            original_question="如何展示？",
            user_feedback=None,
            revision_type="initial",
            plan={},
            answer={"answer": "回答"},
        )
        lessons = RevisionLessonRepository(db)
        first = lessons.add_candidates(
            project_id=project.id,
            source_version_id=version.id,
            candidates=[
                {
                    "type": "presentation_preference",
                    "rule": {"length": "detailed"},
                }
            ],
        )[0]
        second = lessons.add_candidates(
            project_id=project.id,
            source_version_id=version.id,
            candidates=[
                {
                    "type": "presentation_preference",
                    "rule": {"length": "short"},
                }
            ],
        )[0]

        assert first.status == "superseded"
        assert second.status == "active"
        assert second.supersedes_id == first.id
        assert [item.id for item in lessons.list_active(project.id)] == [second.id]


def test_chat_api_creates_root_child_and_confirmation_versions():
    with TestClient(app) as client:
        project = client.post(
            "/projects", json={"name": "回答版本 API 店", "stage": "operating"}
        ).json()
        report = client.post(
            "/operating/analyze-sample",
            json={"project_id": project["id"], "question": "完整分析"},
        ).json()
        root_response = client.post(
            f"/analysis/{report['analysis_id']}/chat",
            json={"question": "当前最优先处理什么？"},
        )
        root = root_response.json()
        child_response = client.post(
            f"/analysis/{report['analysis_id']}/chat",
            json={
                "parent_version_id": root["answer_version_id"],
                "feedback": "回答简短一点",
            },
        )
        child = child_response.json()
        correction_response = client.post(
            f"/analysis/{report['analysis_id']}/chat",
            json={
                "parent_version_id": child["answer_version_id"],
                "feedback": "租金不是 18000，应为 25000",
            },
        )
        correction = correction_response.json()
        versions = client.get(
            f"/analysis/{report['analysis_id']}/answer-versions"
        ).json()

    assert root_response.status_code == 200
    assert root["parent_version_id"] is None
    assert child_response.status_code == 200
    assert child["parent_version_id"] == root["answer_version_id"]
    assert child["revision_plan"]["revision_type"] == "rewrite_only"
    assert correction_response.status_code == 200
    assert correction["mode"] == "confirmation_required"
    assert correction["revision_plan"]["revision_type"] == "recompute_metrics"
    assert len(versions) == 3
    assert versions[-1]["parent_version_id"] == child["answer_version_id"]


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _conversation(db: Session):
    project = Project(name="版本测试店", stage="operating")
    db.add(project)
    db.flush()
    analysis = AnalysisResult(
        project_id=project.id,
        stage="operating",
        summary="摘要",
        metrics_json={},
        evidence_json=[],
        actions_json=[],
        warnings_json=[],
    )
    db.add(analysis)
    db.flush()
    conversation = ConversationRepository(db).get_or_create(
        analysis.id, project.id
    )
    return project, analysis, conversation
