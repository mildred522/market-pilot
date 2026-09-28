from datetime import UTC, datetime

from app.knowledge.contracts import KnowledgeSourceInput
from app.knowledge.document import KnowledgeChunk
from app.knowledge.fact_extractor import DeterministicKnowledgeFactExtractor
from app.knowledge.manifest import KnowledgeAcquisition, KnowledgeManifestEntry


def test_extracts_restaurant_revenue_amount_growth_and_retail_sales():
    facts = DeterministicKnowledgeFactExtractor().extract(
        (
            _chunk(
                "2025年，社会消费品零售总额501202亿元，比上年增长3.7%。"
                "其中餐饮收入57982亿元，同比增长3.2%。"
            ),
        ),
        entry=_entry("government_statistics"),
    )
    by_key = {fact.fact_key: fact for fact in facts}

    assert by_key["market.retail_sales.amount"].value == 501202
    assert by_key["market.retail_sales.amount"].unit == "亿元"
    assert by_key["market.restaurant_revenue.amount"].value == 57982
    assert by_key["market.restaurant_revenue.yoy"].value == 3.2
    assert by_key["market.restaurant_revenue.yoy"].unit == "%"
    assert by_key["market.restaurant_revenue.yoy"].source_chunk_id == "kv1-c0000"
    assert by_key["market.restaurant_revenue.yoy"].review_status == "pending"
    assert by_key["market.restaurant_revenue.yoy"].geography == "成都"


def test_annual_period_beats_monthly_value_on_mixed_statistics_page():
    facts = DeterministicKnowledgeFactExtractor().extract(
        (
            _chunk(
                "按消费类型分，12月份餐饮收入5738亿元，同比增长2.2%。"
                "2025年全年餐饮收入57982亿元，同比增长3.2%。"
            ),
        ),
        entry=_entry("government_statistics"),
    )
    by_key = {fact.fact_key: fact for fact in facts}

    assert by_key["market.restaurant_revenue.amount"].value == 57982
    assert by_key["market.restaurant_revenue.yoy"].value == 3.2


def test_annual_period_beats_monthly_value_across_html_table_cells():
    facts = DeterministicKnowledgeFactExtractor().extract(
        (
            _chunk(
                "按消费类型分，12\n月份\n餐饮收入\n5738\n亿元，增长\n2.2%。"
                "按消费类型分，2025\n年\n餐饮收入\n57982\n亿元，增长\n3.2%。"
                "12月份，社会消费品零售总额\n45136\n亿元。"
                "2025\n年，社会消费品零售总额\n501202\n亿元。"
            ),
        ),
        entry=_entry("government_statistics"),
    )
    by_key = {fact.fact_key: fact for fact in facts}

    assert by_key["market.restaurant_revenue.amount"].value == 57982
    assert by_key["market.restaurant_revenue.yoy"].value == 3.2
    assert by_key["market.retail_sales.amount"].value == 501202


def test_extracts_property_metrics_and_preserves_negative_direction():
    facts = DeterministicKnowledgeFactExtractor(review_status="approved").extract(
        (
            _chunk(
                "成都优质零售物业市场平均空置率收至11.1%，同比上升0.5个百分点；"
                "购物中心首层平均租金同比下跌7.2%，报331.0元/平方米/月。"
            ),
        ),
        entry=_entry("commercial_property"),
    )
    by_key = {fact.fact_key: fact for fact in facts}

    assert by_key["property.retail.vacancy_rate"].value == 11.1
    assert by_key["property.retail.first_floor_rent"].value == 331
    assert by_key["property.retail.first_floor_rent"].unit == "元/平方米/月"
    assert all(fact.review_status == "approved" for fact in facts)


def test_property_rules_ignore_office_metrics_before_retail_section():
    facts = DeterministicKnowledgeFactExtractor().extract(
        (
            _chunk(
                "成都甲级办公楼市场平均空置率32.0%，平均租金78.7元/平方米/月。"
                "成都优质零售地产平均空置率11.2%，"
                "全市购物中心首层平均租金为353.0元/平方米/月。"
            ),
        ),
        entry=_entry("commercial_property"),
    )
    by_key = {fact.fact_key: fact for fact in facts}

    assert by_key["property.retail.vacancy_rate"].value == 11.2
    assert by_key["property.retail.first_floor_rent"].value == 353


def test_extracts_wage_median_from_five_quantile_table():
    facts = DeterministicKnowledgeFactExtractor().extract(
        (_chunk("餐饮服务人员 | 2.40 | 2.88 | 3.60 | 4.80 | 6.60"),),
        entry=_entry("government_statistics"),
    )

    assert len(facts) == 1
    assert facts[0].fact_key == "labor.wage.catering_service.p50"
    assert facts[0].value == 3.6
    assert facts[0].unit == "万元/年"


def test_absolute_annual_wage_uses_yuan_unit():
    facts = DeterministicKnowledgeFactExtractor().extract(
        (_chunk("住宿和餐饮服务人员 28878 33600 41270 53199 68579"),),
        entry=_entry("government_statistics"),
    )

    assert facts[0].value == 41270
    assert facts[0].unit == "元/年"


def test_mixed_documents_do_not_emit_ambiguous_facts():
    entry = _entry("industry_report").model_copy(update={"fact_status": "mixed"})

    facts = DeterministicKnowledgeFactExtractor().extract(
        (_chunk("餐饮收入达到100亿元，同比增长9%。"),),
        entry=entry,
    )

    assert facts == ()


def _entry(source_type: str) -> KnowledgeManifestEntry:
    return KnowledgeManifestEntry(
        source=KnowledgeSourceInput(
            source_key=f"fact-test-{source_type.replace('_', '-')}",
            title="成都餐饮指标资料",
            publisher="测试发布方",
            source_type=source_type,
            canonical_url="https://example.com/report",
            reliability_tier=1,
            default_city="成都",
            default_category="餐饮",
        ),
        acquisition=KnowledgeAcquisition(
            local_path="report.md",
            allowed_media_types=("text/markdown",),
        ),
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        data_period_start=datetime(2025, 1, 1, tzinfo=UTC),
        data_period_end=datetime(2025, 12, 31, tzinfo=UTC),
        fact_status="observed",
        cities=("成都",),
        categories=("餐饮",),
    )


def _chunk(text: str) -> KnowledgeChunk:
    return KnowledgeChunk(
        point_id="00000000-0000-0000-0000-000000000001",
        chunk_id="kv1-c0000",
        document_version_id=1,
        chunk_index=0,
        content_hash="a" * 64,
        raw_text=text,
        retrieval_text=text,
        payload={},
    )
