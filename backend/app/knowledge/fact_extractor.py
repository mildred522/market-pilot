from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.knowledge.contracts import KnowledgeFactInput, KnowledgeReviewStatus
from app.knowledge.document import KnowledgeChunk
from app.knowledge.manifest import KnowledgeManifestEntry


@dataclass(frozen=True)
class MetricRule:
    fact_key: str
    label: str
    pattern: re.Pattern[str]
    fixed_unit: str | None = None
    value_group: str = "value"
    unit_group: str | None = "unit"
    direction_group: str | None = None


AMOUNT_UNIT = r"万亿元|亿元|万元|元"
NUMBER = r"\d+(?:,\d{3})*(?:\.\d+)?"

METRIC_RULES: tuple[MetricRule, ...] = (
    MetricRule(
        fact_key="market.restaurant_revenue.amount",
        label="餐饮收入",
        pattern=re.compile(
            rf"餐饮收入(?:达到|达|为|实现)?\s*(?P<value>{NUMBER})\s*(?P<unit>{AMOUNT_UNIT})"
        ),
    ),
    MetricRule(
        fact_key="market.restaurant_revenue.yoy",
        label="餐饮收入同比增速",
        pattern=re.compile(
            rf"餐饮收入.{{0,48}}?(?:同比)?(?P<direction>增长|下降)\s*(?P<value>{NUMBER})\s*%",
            re.DOTALL,
        ),
        fixed_unit="%",
        unit_group=None,
        direction_group="direction",
    ),
    MetricRule(
        fact_key="market.retail_sales.amount",
        label="社会消费品零售总额",
        pattern=re.compile(
            rf"社会消费品零售总额(?:达到|达|为|实现)?\s*(?P<value>{NUMBER})\s*(?P<unit>{AMOUNT_UNIT})"
        ),
    ),
    MetricRule(
        fact_key="property.retail.vacancy_rate",
        label="零售物业空置率",
        pattern=re.compile(
            rf"(?:优质)?(?:零售地产|零售物业|购物中心|商场).{{0,60}}?"
            rf"(?:平均)?空置率.{{0,28}}?(?:为|至|收至|约)?\s*(?P<value>{NUMBER})\s*%",
            re.DOTALL,
        ),
        fixed_unit="%",
        unit_group=None,
    ),
    MetricRule(
        fact_key="property.retail.first_floor_rent",
        label="零售物业首层平均租金",
        pattern=re.compile(
            rf"(?:优质)?(?:零售地产|零售物业|购物中心|商场).{{0,70}}?"
            rf"(?:首层|一层).{{0,16}}?(?:平均)?租金.{{0,35}}?"
            rf"(?:至|为|报|约)?\s*(?P<value>{NUMBER})\s*(?:元|人民币)"
            rf"\s*(?:/|每)\s*(?:平方米|平米)\s*(?:/|每)\s*月",
            re.DOTALL,
        ),
        fixed_unit="元/平方米/月",
        unit_group=None,
    ),
)

WAGE_MEDIAN_PATTERN = re.compile(
    rf"(?P<label>住宿和餐饮服务人员|餐饮服务人员|餐厅服务员)"
    rf"[^0-9]{{0,30}}(?P<p10>{NUMBER})[^0-9]+(?P<p25>{NUMBER})"
    rf"[^0-9]+(?P<p50>{NUMBER})[^0-9]+(?P<p75>{NUMBER})"
    rf"[^0-9]+(?P<p90>{NUMBER})",
    re.DOTALL,
)


class DeterministicKnowledgeFactExtractor:
    version = "deterministic-facts-v1"

    def __init__(
        self,
        *,
        review_status: KnowledgeReviewStatus = "pending",
    ) -> None:
        self._review_status = review_status

    @property
    def review_status(self) -> KnowledgeReviewStatus:
        return self._review_status

    def extract(
        self,
        chunks: tuple[KnowledgeChunk, ...],
        *,
        entry: KnowledgeManifestEntry,
    ) -> tuple[KnowledgeFactInput, ...]:
        if entry.fact_status == "mixed":
            return ()
        facts: dict[str, KnowledgeFactInput] = {}
        for rule in METRIC_RULES:
            candidate = _best_rule_match(chunks, rule, entry)
            if candidate is None:
                continue
            chunk, match = candidate
            value = _numeric_value(match.group(rule.value_group))
            if rule.direction_group and match.group(rule.direction_group) == "下降":
                value = -value
            unit = rule.fixed_unit or match.group(rule.unit_group or "")
            facts[rule.fact_key] = self._fact(
                fact_key=rule.fact_key,
                label=rule.label,
                value=value,
                unit=unit,
                source_chunk_id=chunk.chunk_id,
                entry=entry,
            )

        for chunk in chunks:
            wage_match = WAGE_MEDIAN_PATTERN.search(chunk.raw_text)
            if wage_match is not None:
                wage_key = _wage_fact_key(wage_match.group("label"))
                if wage_key not in facts:
                    wage_value = _numeric_value(wage_match.group("p50"))
                    facts[wage_key] = self._fact(
                        fact_key=wage_key,
                        label=f"{wage_match.group('label')}工资中位数",
                        value=wage_value,
                        unit="元/年" if wage_value >= 1000 else "万元/年",
                        source_chunk_id=chunk.chunk_id,
                        entry=entry,
                    )
        return tuple(facts.values())

    def _fact(
        self,
        *,
        fact_key: str,
        label: str,
        value: int | float,
        unit: str,
        source_chunk_id: str,
        entry: KnowledgeManifestEntry,
    ) -> KnowledgeFactInput:
        return KnowledgeFactInput(
            fact_key=fact_key,
            label=label,
            value=value,
            unit=unit,
            geography=_geography(entry),
            category=(
                entry.categories[0]
                if len(entry.categories) == 1
                else entry.source.default_category
            ),
            observed_or_forecast=_fact_status(entry.fact_status),
            source_chunk_id=source_chunk_id,
            valid_from=entry.data_period_start,
            valid_to=entry.data_period_end,
            review_status=self._review_status,
        )


def _numeric_value(value: str) -> int | float:
    normalized = value.replace(",", "")
    number = float(normalized)
    return int(number) if number.is_integer() else number


def _best_rule_match(
    chunks: tuple[KnowledgeChunk, ...],
    rule: MetricRule,
    entry: KnowledgeManifestEntry,
) -> tuple[KnowledgeChunk, re.Match[str]] | None:
    candidates: list[tuple[int, int, KnowledgeChunk, re.Match[str]]] = []
    for chunk_index, chunk in enumerate(chunks):
        for match in rule.pattern.finditer(chunk.raw_text):
            context = _sentence_context(chunk.raw_text, match.start(), match.end())
            score = _period_alignment_score(context, entry)
            candidates.append((score, -chunk_index, chunk, match))
    if not candidates:
        return None
    _, _, chunk, match = max(candidates, key=lambda item: (item[0], item[1]))
    return chunk, match


def _period_alignment_score(context: str, entry: KnowledgeManifestEntry) -> int:
    compact_context = re.sub(r"\s+", "", context)
    score = 0
    if re.search(r"全年|1[—–-]12月|年度", compact_context):
        score += 6
    if re.search(r"20\d{2}年(?!\d{1,2}月)", compact_context):
        score += 3
    if (
        entry.data_period_end is not None
        and f"{entry.data_period_end.year}年" in compact_context
    ):
        score += 3
    if re.search(r"(?:^|[^0-9])12月份", compact_context):
        score -= 6
    if re.search(r"当月|单月", compact_context):
        score -= 4
    return score


def _sentence_context(text: str, start: int, end: int) -> str:
    left_boundaries = [text.rfind(mark, 0, start) for mark in "。！？"]
    left = max(max(left_boundaries) + 1, start - 160)
    right_candidates = [
        index
        for mark in "。！？"
        if (index := text.find(mark, end)) >= 0
    ]
    sentence_right = min(right_candidates) + 1 if right_candidates else len(text)
    right = min(sentence_right, end + 160)
    return text[left:right]


def _geography(entry: KnowledgeManifestEntry) -> str | None:
    if len(entry.cities) == 1:
        return entry.cities[0]
    return entry.source.default_city


def _fact_status(value: str) -> Literal["observed", "forecast"]:
    return "forecast" if value == "forecast" else "observed"


def _wage_fact_key(label: str) -> str:
    return {
        "住宿和餐饮服务人员": "labor.wage.accommodation_and_catering.p50",
        "餐饮服务人员": "labor.wage.catering_service.p50",
        "餐厅服务员": "labor.wage.restaurant_server.p50",
    }[label]
