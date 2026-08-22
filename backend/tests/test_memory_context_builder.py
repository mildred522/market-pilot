from app.memory.context_builder import build_conversation_context
from app.memory.contracts import PublicMemoryMessage


def test_context_keeps_only_latest_six_public_messages_and_marks_them_untrusted():
    messages = [
        PublicMemoryMessage(
            role="user" if index % 2 == 0 else "assistant",
            content=f"message-{index}",
            mode="public",
            evidence_refs=[],
            tool_calls=[],
        )
        for index in range(8)
    ]

    context = build_conversation_context(messages)

    assert context["trust"] == "untrusted_historical_context"
    assert [item["content"] for item in context["messages"]] == [
        f"message-{index}" for index in range(2, 8)
    ]
    assert "summary" not in context


def test_followup_prompt_keeps_current_report_separate_from_history():
    class CapturingClient:
        configured = True
        provider = "fake"
        model = "fake"

        def __init__(self):
            self.prompt = ""

        def generate_json(self, *, user_prompt, **_kwargs):
            self.prompt = user_prompt
            return FollowupStep(
                action="answer",
                answer="当前报告结论保持不变。",
                evidence_refs=["report.summary"],
                confidence=0.9,
            )

    client = CapturingClient()
    context = build_conversation_context(
        [
            PublicMemoryMessage(
                role="user",
                content="上一轮问题",
                mode="public",
                evidence_refs=[],
                tool_calls=[],
            )
        ]
    )

    ReportFollowupAgent(client).answer(
        question="继续解释",
        summary="当前报告摘要",
        metrics={"revenue": {"total_revenue": 336}},
        evidence=[],
        actions=[],
        risks=[],
        conversation_context=context,
    )

    prompt = json.loads(client.prompt)
    assert prompt["conversation_history"]["trust"] == "untrusted_historical_context"
    assert prompt["conversation_history"]["messages"][0]["content"] == "上一轮问题"
    facts = {
        item["canonical_ref"]: item
        for item in prompt["evidence_pack"]["facts"]
    }
    assert facts["report.summary"]["value"] == "当前报告摘要"
import json

from app.agent_runtime.contracts import FollowupStep
from app.agent_runtime.followup import ReportFollowupAgent
