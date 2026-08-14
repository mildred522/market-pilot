from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.db.models import (
    AnalysisConversation,
    AnalysisMessage,
    AnalysisResult,
    Base,
    Project,
)
from app.memory.repository import ConversationRepository
from app.db.session import SessionLocal
from app.main import app


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_repository_persists_only_public_exchange_fields():
    with _session() as db:
        project = Project(name="记忆测试店", stage="operating")
        db.add(project)
        db.flush()
        result = AnalysisResult(
            project_id=project.id,
            stage="operating",
            summary="报告摘要",
            metrics_json={},
            evidence_json=[],
            actions_json=[],
            warnings_json=[],
        )
        db.add(result)
        db.flush()
        repository = ConversationRepository(db)
        conversation = repository.get_or_create(
            analysis_id=result.id, project_id=project.id
        )

        repository.append_exchange(
            conversation_id=conversation.id,
            question="上一轮的客单价是多少？",
            answer={
                "answer": "客单价为 42 元。",
                "mode": "llm",
                "evidence_refs": ["metrics.revenue.avg_order_value"],
                "tool_calls": [{
                    "tool": "read_metric",
                    "arguments": {"path": "metrics.revenue.avg_order_value"},
                    "provider_response": "must not persist",
                }],
                "failure_detail": {"candidate": "private rejected output"},
            },
        )
        db.commit()

        messages = db.scalars(
            select(AnalysisMessage).order_by(AnalysisMessage.id)
        ).all()
        assert [message.role for message in messages] == ["user", "assistant"]
        assert messages[1].content == "客单价为 42 元。"
        assert messages[1].evidence_refs_json == ["metrics.revenue.avg_order_value"]
        assert messages[1].tool_calls_json[0]["tool"] == "read_metric"
        assert "provider_response" not in messages[1].tool_calls_json[0]
        assert "private rejected output" not in str(messages[1].__dict__)


def test_get_or_create_reuses_one_conversation_per_analysis():
    with _session() as db:
        project = Project(name="单会话测试店", stage="operating")
        db.add(project)
        db.flush()
        result = AnalysisResult(
            project_id=project.id,
            stage="operating",
            summary="摘要",
            metrics_json={},
            evidence_json=[],
            actions_json=[],
            warnings_json=[],
        )
        db.add(result)
        db.flush()
        repository = ConversationRepository(db)

        first = repository.get_or_create(result.id, project.id)
        second = repository.get_or_create(result.id, project.id)

        assert first.id == second.id
        assert len(db.scalars(select(AnalysisConversation)).all()) == 1


def test_analysis_chat_api_persists_public_question_and_answer():
    with TestClient(app) as client:
        project = client.post(
            "/projects", json={"name": "API 记忆店", "stage": "operating"}
        ).json()
        report = client.post(
            "/operating/analyze-sample",
            json={"project_id": project["id"], "question": "完整分析"},
        ).json()
        response = client.post(
            f"/analysis/{report['analysis_id']}/chat",
            json={"question": "这份报告的结论是什么？"},
        )

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["conversation_id"], int)
    with SessionLocal() as db:
        conversation = db.get(AnalysisConversation, body["conversation_id"])
        assert conversation is not None
        messages = db.scalars(
            select(AnalysisMessage)
            .where(AnalysisMessage.conversation_id == conversation.id)
            .order_by(AnalysisMessage.id)
        ).all()
        assert [message.role for message in messages] == ["user", "assistant"]
        assert messages[0].content == "这份报告的结论是什么？"
        assert messages[1].content == body["answer"]
