from __future__ import annotations

import json
import re

from app.agent_runtime.contracts import LlmCallMetadata, RevisionPlan
from app.agent_runtime.llm_client import LlmClient, LlmError, generate_json_with_metadata
from app.agent_runtime.prompts import REVISION_PLANNER_SYSTEM_PROMPT


def create_revision_plan(
    *,
    client: LlmClient,
    original_question: str,
    prior_answer: dict[str, object],
    feedback: str,
) -> tuple[RevisionPlan, list[LlmCallMetadata]]:
    fallback = _fallback_revision_plan(feedback)
    if not client.configured:
        return fallback, []
    try:
        generation = generate_json_with_metadata(
            client=client,
            role="revision_planner",
            system_prompt=REVISION_PLANNER_SYSTEM_PROMPT,
            user_prompt=json.dumps(
                {
                    "original_question": original_question,
                    "prior_answer": prior_answer,
                    "user_feedback": feedback,
                },
                ensure_ascii=False,
                default=str,
            ),
            response_model=RevisionPlan,
            temperature=0.1,
        )
        return generation.output, [generation.metadata]
    except (LlmError, ValueError) as error:
        metadata = error.metadata if isinstance(error, LlmError) else None
        return fallback, [metadata] if metadata is not None else []


def _fallback_revision_plan(feedback: str) -> RevisionPlan:
    if any(keyword in feedback for keyword in ("不是", "改成", "应为", "写错", "纠正")):
        revision_type = "recompute_metrics"
    elif any(
        keyword in feedback
        for keyword in ("趋势", "行业", "成都", "当地", "附近", "竞品", "上次", "历史")
    ):
        revision_type = "retrieve_more_evidence"
    elif any(keyword in feedback for keyword in ("不要", "别推荐", "换个重点")):
        revision_type = "recompose_with_existing_evidence"
    else:
        revision_type = "rewrite_only"
    return RevisionPlan(
        revision_type=revision_type,
        objective=feedback[:400],
        preserve_existing_evidence=revision_type != "recompute_metrics",
        requires_confirmation=revision_type == "recompute_metrics",
        corrections=_extract_explicit_corrections(feedback),
        lessons=[],
    )


_CORRECTION_ALIASES = {
    "monthly_rent": ("月租", "租金", "房租"),
    "monthly_labor": ("人工成本", "人工", "工资"),
    "monthly_utilities": ("水电成本", "水电费", "水电"),
    "monthly_marketing": ("营销费用", "营销费", "推广费"),
    "other_fixed_costs": ("其他固定成本", "杂费"),
    "cash_balance": ("现金余额", "现金"),
    "delivery_commission_rate": ("外卖佣金率", "佣金率", "外卖佣金"),
    "delivery_packaging_per_order": ("单均包材成本", "包材成本", "打包成本"),
}


def _extract_explicit_corrections(feedback: str) -> list[dict[str, object]]:
    candidates = []
    for field, aliases in _CORRECTION_ALIASES.items():
        alias = next((item for item in aliases if item in feedback), None)
        if alias is None:
            continue
        tail = feedback.split(alias, 1)[1]
        values = list(re.finditer(r"(\d+(?:\.\d+)?)\s*(万|千|%|％)?", tail))
        if not values:
            continue
        match = values[-1]
        value = float(match.group(1))
        unit = match.group(2)
        if unit == "万":
            value *= 10000
        elif unit == "千":
            value *= 1000
        elif unit in {"%", "％"}:
            value /= 100
        if field == "delivery_commission_rate" and value > 1:
            continue
        candidates.append(
            {"field": field, "new_value": value, "reason": feedback[:300]}
        )
    return candidates[:3]
