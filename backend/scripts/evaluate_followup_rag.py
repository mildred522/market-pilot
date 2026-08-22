from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent_runtime.contracts import (
    FollowupAnswerSections,
    FollowupDataClaim,
    FollowupEvidenceRequest,
    FollowupStep,
)
from app.agent_runtime.followup import ReportFollowupAgent
from app.agent_runtime.llm_client import (
    OpenAiCompatibleLlmClient,
    llm_client_from_environment,
)
from app.db.models import AnalysisResult
from app.external_context.followup_provider import PersistedFollowupEvidenceProvider
from app.knowledge.factory import build_knowledge_retrieval_service
from app.memory.project_profile import ProjectProfileService
from app.services.runtime_config import runtime_config


class ScriptedRagFollowupClient:
    configured = True
    provider = "scripted-eval"
    model = "deterministic-followup-rag"

    def __init__(self) -> None:
        self.calls = 0
        self.external_facts: list[dict] = []

    def generate_json(self, *, user_prompt: str, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return FollowupStep(
                action="retrieve",
                evidence_requests=[
                    FollowupEvidenceRequest(
                        capability="external_industry_context",
                        purpose="结合成都和新茶饮行业材料提出上新建议",
                        requirement="required",
                        success_condition="返回带发布方、日期和适用边界的行业证据",
                    )
                ],
            )

        prompt = json.loads(user_prompt)
        self.external_facts = [
            fact
            for fact in prompt["evidence_pack"]["facts"]
            if fact["source"] == "external_context"
            and fact.get("provenance", {}).get("retrieval_mode")
            == "hybrid_reranked"
        ]
        product_fact = next(
            (
                fact
                for fact in self.external_facts
                if "上新能力成为核心能力" in str(fact["value"])
            ),
            self.external_facts[0] if self.external_facts else None,
        )
        if product_fact is None:
            return FollowupStep(
                action="insufficient_data",
                answer="没有取得可核验的行业知识片段。",
                confidence=0.2,
            )
        return FollowupStep(
            action="answer",
            sections=FollowupAnswerSections(
                data_findings=[
                    FollowupDataClaim(
                        text="行业材料认为，持续上新是茶饮品牌保持差异化的重要能力。",
                        evidence_ids=[product_fact["id"]],
                    )
                ],
                general_advice=[
                    "优先小批量测试门店现有顾客容易理解的季节新品。",
                    "先比较新品毛利、复购和制作时长，再决定是否扩大投放。",
                ],
                missing_information=[
                    "全国行业材料不能直接证明成都具体商圈偏好，仍需本店试销数据。"
                ],
            ),
            confidence=0.88,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a scripted or live model against the follow-up RAG path."
    )
    parser.add_argument("--database", type=Path, default=Path("restaurant_agent.db"))
    parser.add_argument("--analysis-id", type=int, default=None)
    parser.add_argument(
        "--question",
        default="结合成都和新茶饮行业趋势，根据当前经营报告推荐上新方向",
    )
    parser.add_argument(
        "--client",
        choices=("scripted", "live"),
        default="scripted",
        help="Use the deterministic baseline or the configured Agent API.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Temporarily override the configured model for a live evaluation.",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    engine = create_engine(f"sqlite:///{args.database.resolve().as_posix()}")
    with Session(engine) as db:
        analysis = (
            db.get(AnalysisResult, args.analysis_id)
            if args.analysis_id is not None
            else db.scalar(
                select(AnalysisResult)
                .where(AnalysisResult.stage == "operating")
                .order_by(AnalysisResult.id.desc())
                .limit(1)
            )
        )
        if analysis is None:
            parser.error("no matching operating analysis exists")

        metrics = ProjectProfileService(db).enrich_metrics(
            analysis.project_id, analysis.metrics_json
        )
        profile = dict(metrics.get("_project_profile", {}))
        profile.update({"city": "成都", "category": "新茶饮"})
        metrics["_project_profile"] = profile

        settings = runtime_config.knowledge_rag_settings()
        knowledge_service = build_knowledge_retrieval_service(db, settings)
        if args.client == "scripted":
            client = ScriptedRagFollowupClient()
        elif args.model:
            client = OpenAiCompatibleLlmClient(
                api_key=runtime_config.get("agent_api_key", "AGENT_LLM_API_KEY"),
                model=args.model,
                base_url=runtime_config.get(
                    "agent_base_url", "AGENT_LLM_BASE_URL"
                ),
                provider=runtime_config.get(
                    "agent_provider", "AGENT_LLM_PROVIDER", "openai-compatible"
                ),
            )
        else:
            client = llm_client_from_environment("followup")
        if not client.configured:
            parser.error("the live Agent API is not configured")
        answer = ReportFollowupAgent(client).answer(
            question=args.question,
            summary=analysis.summary,
            metrics=metrics,
            evidence=analysis.evidence_json,
            actions=analysis.actions_json,
            risks=analysis.warnings_json,
            evidence_provider=PersistedFollowupEvidenceProvider(
                db,
                project_id=analysis.project_id,
                knowledge_service=knowledge_service,
            ),
        )

    external_facts = getattr(client, "external_facts", [])
    model_calls = answer.get("llm_calls", [])
    retrieved_rag_facts = [
        {
            "id": fact["id"],
            "canonical_ref": fact["canonical_ref"],
            "retrieval_mode": fact["provenance"].get("retrieval_mode"),
            "publisher": fact["provenance"].get("publisher"),
            "published_at_ts": fact["provenance"].get("published_at_ts"),
        }
        for fact in external_facts
    ]
    if not retrieved_rag_facts:
        retrieved_rag_facts = [
            {
                "id": None,
                "canonical_ref": reference,
                "retrieval_mode": None,
                "publisher": None,
                "published_at_ts": None,
            }
            for event in answer.get("agent_trace", {}).get("evidence_events", [])
            for reference in event.get("evidence_refs", [])
            if reference.startswith("external.knowledge.")
        ]
    report = {
        "analysis_id": analysis.id,
        "project_id": analysis.project_id,
        "question": args.question,
        "client": args.client,
        "provider": client.provider,
        "model": client.model,
        "rag_enabled": settings.enabled,
        "rerank_enabled": settings.rerank_enabled,
        "planner_calls": getattr(client, "calls", len(model_calls)),
        "retrieved_rag_facts": retrieved_rag_facts,
        "answer": answer,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "analysis_id": analysis.id,
                    "client": args.client,
                    "provider": client.provider,
                    "model": client.model,
                    "planner_calls": getattr(client, "calls", len(model_calls)),
                    "retrieved_rag_facts": len(retrieved_rag_facts),
                    "quality": answer.get("quality"),
                    "mode": answer.get("mode"),
                    "tool_calls": answer.get("tool_calls"),
                    "evidence_refs": answer.get("evidence_refs"),
                    "answer": answer.get("answer"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
