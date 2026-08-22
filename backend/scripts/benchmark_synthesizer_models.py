from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from app.agent_runtime.contracts import AgentPlan, PlannedTool
from app.agent_runtime.llm_client import OpenAiCompatibleLlmClient
from app.agent_runtime.synthesis import synthesize_operating_report
from app.agent_runtime.tools import (
    CORE_OPERATING_TOOLS,
    OperatingToolContext,
    execute_operating_tools,
)
from app.agents.state import AgentState
from app.services.runtime_config import runtime_config


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare report models against identical operating metrics."
    )
    parser.add_argument(
        "--models", nargs="+", required=True, help="Provider model IDs to compare."
    )
    parser.add_argument(
        "--question", default="综合分析当前门店经营状况并给出优先行动。"
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    context = OperatingToolContext(
        orders=pd.read_csv(root / "sample_data/orders.csv"),
        menu=pd.read_csv(root / "sample_data/menu_items.csv"),
        reviews=pd.read_csv(root / "sample_data/reviews.csv"),
        cost_assumptions=_cost_assumptions(),
    )
    batch = execute_operating_tools(list(CORE_OPERATING_TOOLS), context)
    if batch.status == "failed":
        parser.error("deterministic operating tools failed")
    plan = AgentPlan(
        intent="operating_diagnosis",
        goal="identify the highest-priority operating actions",
        tools=[
            PlannedTool(name=name, reason="fixed benchmark tool set")
            for name in CORE_OPERATING_TOOLS
        ],
        missing_inputs=[],
        requires_external_api=False,
    )
    base_state = AgentState(
        project_id=0,
        question=args.question,
        stage="operating",
        intent=plan.intent,
        plan=[*CORE_OPERATING_TOOLS, "generate_recommendations"],
        tool_results=batch.successful_data,
    )

    rows = []
    for model in args.models:
        metadata = []
        state, used_llm, fallbacks = synthesize_operating_report(
            client=_client(model),
            state=deepcopy(base_state),
            plan=plan,
            metadata_sink=metadata,
        )
        rows.append(
            {
                "model": model,
                "used_llm": used_llm,
                "fallbacks": fallbacks,
                "summary": state.summary,
                "evidence": state.evidence,
                "actions": state.actions,
                "warnings": state.warnings,
                "llm_calls": [item.model_dump(mode="json") for item in metadata],
            }
        )
    report = {"question": args.question, "models": rows}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "models": [
                        {
                            "model": row["model"],
                            "used_llm": row["used_llm"],
                            "fallbacks": row["fallbacks"],
                            "calls": row["llm_calls"],
                            "evidence_count": len(row["evidence"]),
                            "action_count": len(row["actions"]),
                        }
                        for row in rows
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(rendered)
    return 0


def _client(model: str) -> OpenAiCompatibleLlmClient:
    return OpenAiCompatibleLlmClient(
        api_key=runtime_config.get("agent_api_key", "AGENT_LLM_API_KEY"),
        model=model,
        base_url=runtime_config.get("agent_base_url", "AGENT_LLM_BASE_URL"),
        provider=runtime_config.get(
            "agent_provider", "AGENT_LLM_PROVIDER", "openai-compatible"
        ),
    )


def _cost_assumptions() -> dict[str, float]:
    return {
        "monthly_rent": 18000.0,
        "monthly_labor": 24000.0,
        "monthly_utilities": 3000.0,
        "monthly_marketing": 2000.0,
        "other_fixed_costs": 3000.0,
        "cash_balance": 120000.0,
        "delivery_commission_rate": 0.2,
        "delivery_packaging_per_order": 1.5,
    }


if __name__ == "__main__":
    raise SystemExit(main())
