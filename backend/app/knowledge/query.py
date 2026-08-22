from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.agent_runtime.followup_evidence import EvidenceRetrievalContext


class KnowledgeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1, max_length=2400)
    city: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=80)
    as_of: datetime
    requires_current: bool = False
    include_forecasts: bool = False
    allowed_source_types: tuple[str, ...] = ()
    max_reliability_tier: int = Field(default=2, ge=1, le=4)
    limit: int = Field(default=8, ge=1, le=12)


class KnowledgeQueryCompiler:
    def compile(self, context: EvidenceRetrievalContext) -> KnowledgeQuery:
        profile = context.project_profile
        question = context.question.strip()
        purpose = context.purpose.strip()
        return KnowledgeQuery(
            text=f"{question}\n检索目的：{purpose}",
            city=_normalize_city(profile.get("city")),
            category=_normalize_category(profile.get("category")),
            as_of=context.as_of,
            requires_current=_contains_any(
                question,
                ("当前", "目前", "最新", "最近", "现在", "现状"),
            ),
            include_forecasts=_contains_any(
                question,
                ("预测", "预计", "未来", "趋势", "潜力", "前景"),
            ),
            allowed_source_types=_source_types(question),
            max_reliability_tier=2,
        )


def _normalize_city(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    aliases = {
        "chengdu": "成都",
        "成都市": "成都",
    }
    return aliases.get(normalized.lower(), normalized.removesuffix("市"))


def _normalize_category(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    aliases = {
        "milk-tea": "新茶饮",
        "milk_tea": "新茶饮",
        "奶茶": "新茶饮",
        "现制茶饮": "新茶饮",
        "food-service": "餐饮",
    }
    return aliases.get(normalized.lower(), normalized)


def _source_types(question: str) -> tuple[str, ...]:
    if _contains_any(question, ("法规", "规定", "合规", "许可证", "标准")):
        return ("regulation", "government_statistics")
    return (
        "government_statistics",
        "official_statistics",
        "industry_association",
        "listed_company_filing",
        "industry_report",
        "web_article",
        "internal_methodology",
    )


def _contains_any(value: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in value for keyword in keywords)
