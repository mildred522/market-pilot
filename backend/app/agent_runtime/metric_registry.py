from __future__ import annotations

from dataclasses import asdict, dataclass
from fnmatch import fnmatchcase
from typing import Any


@dataclass(frozen=True)
class MetricDefinition:
    path: str
    label: str
    description: str
    value_type: str
    unit: str = "none"
    formula: str | None = None
    direction: str = "context_dependent"
    benchmark_required: bool = False
    source_tool: str = ""
    scope: str = "当前报告样本期"
    includes: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    related_metrics: tuple[str, ...] = ()
    item_schema: dict[str, str] | None = None

    def context(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in (None, (), {}, "")}


def _m(
    path: str,
    label: str,
    description: str,
    value_type: str,
    **kwargs: Any,
) -> MetricDefinition:
    return MetricDefinition(path, label, description, value_type, **kwargs)


METRICS: tuple[MetricDefinition, ...] = (
    _m("metrics.revenue.total_revenue", "总营收", "样本期订单实收金额合计", "number", unit="currency", formula="sum(actual_amount)", direction="higher_is_better", benchmark_required=True, source_tool="analyze_revenue"),
    _m("metrics.revenue.order_count", "订单数", "样本期去重订单数量", "integer", unit="orders", formula="count_distinct(order_id)", direction="higher_is_better", benchmark_required=True, source_tool="analyze_revenue"),
    _m("metrics.revenue.avg_order_value", "客单价", "样本期实收营收除以订单数", "number", unit="currency_per_order", formula="total_revenue / order_count", direction="higher_is_better", benchmark_required=True, source_tool="analyze_revenue"),
    _m("metrics.revenue.daily_revenue", "每日营收", "按有订单日期聚合的营收和订单数", "array", source_tool="analyze_revenue", limitations=("缺失日期不会自动补零",), item_schema={"date": "营业日期 YYYY-MM-DD", "revenue": "当日实收营收/元", "orders": "当日去重订单数"}),

    _m("metrics.channels.channels", "渠道明细", "按堂食、外卖等渠道汇总的经营贡献", "array", source_tool="analyze_channel_profitability", scope="当前报告样本期各渠道", excludes=("房租", "人工", "水电", "营销等固定成本"), item_schema={"channel": "原始渠道名称", "channel_type": "delivery 或 direct", "order_count": "渠道订单数", "revenue": "渠道实收营收/元", "revenue_share": "渠道营收占总营收比例", "average_order_value": "渠道客单价/元", "food_cost": "渠道食材成本/元", "platform_fee": "渠道平台佣金/元", "packaging_cost": "渠道包材成本/元", "contribution_profit": "扣直接成本后的贡献利润/元", "contribution_margin": "贡献利润除以渠道营收"}),
    _m("metrics.channels.delivery_commission_rate", "外卖佣金率", "计算外卖平台佣金时采用的假设比例", "number", unit="ratio", source_tool="analyze_channel_profitability", scope="用户输入假设", benchmark_required=True),
    _m("metrics.channels.delivery_packaging_per_order", "单均外卖包材成本", "每个外卖订单采用的包材成本假设", "number", unit="currency_per_order", source_tool="analyze_channel_profitability", scope="用户输入假设", benchmark_required=True),
    _m("metrics.channels.delivery_revenue", "外卖营收", "所有外卖渠道实收营收合计", "number", unit="currency", formula="sum(delivery channel revenue)", direction="higher_is_better", benchmark_required=True, source_tool="analyze_channel_profitability"),
    _m("metrics.channels.delivery_revenue_share", "外卖营收占比", "外卖营收占样本总营收比例；不是外卖贡献率", "number", unit="ratio", formula="delivery_revenue / total_revenue", benchmark_required=True, source_tool="analyze_channel_profitability", related_metrics=("metrics.channels.delivery_contribution_margin", "metrics.revenue.total_revenue")),
    _m("metrics.channels.delivery_food_cost", "外卖食材成本", "外卖订单菜品食材成本合计", "number", unit="currency", formula="sum(quantity * unit_cost)", direction="lower_is_better", benchmark_required=True, source_tool="analyze_channel_profitability"),
    _m("metrics.channels.delivery_platform_fee", "外卖平台佣金", "外卖营收乘佣金率所得的平台费用", "number", unit="currency", formula="delivery_revenue * delivery_commission_rate", direction="lower_is_better", benchmark_required=True, source_tool="analyze_channel_profitability"),
    _m("metrics.channels.delivery_packaging_cost", "外卖包材成本", "外卖订单数乘单均包材成本", "number", unit="currency", formula="delivery_order_count * delivery_packaging_per_order", direction="lower_is_better", benchmark_required=True, source_tool="analyze_channel_profitability"),
    _m("metrics.channels.delivery_contribution_profit", "外卖贡献利润", "外卖营收扣除食材、平台佣金和包材后的利润", "number", unit="currency", formula="delivery_revenue - food_cost - platform_fee - packaging_cost", direction="higher_is_better", benchmark_required=True, source_tool="analyze_channel_profitability", includes=("食材成本", "平台佣金", "包材成本"), excludes=("房租", "人工", "水电", "营销等固定成本")),
    _m("metrics.channels.delivery_contribution_margin", "外卖贡献率", "外卖贡献利润占外卖营收比例；不是外卖营收占比", "number", unit="ratio", formula="delivery_contribution_profit / delivery_revenue", direction="higher_is_better", benchmark_required=True, source_tool="analyze_channel_profitability", includes=("食材成本", "平台佣金", "包材成本"), excludes=("房租", "人工", "水电", "营销等固定成本"), related_metrics=("metrics.channels.delivery_revenue_share", "metrics.channels.delivery_contribution_profit")),
    _m("metrics.channels.assumption_note", "渠道分析边界", "渠道贡献利润的口径和未覆盖成本", "string", source_tool="analyze_channel_profitability"),

    _m("metrics.time_patterns.observed_days", "有订单营业日数", "CSV 中出现至少一笔订单的日期数量", "integer", unit="days", source_tool="analyze_time_patterns", limitations=("无订单日期不会自动视为零营收",)),
    _m("metrics.time_patterns.dayparts", "时段表现", "按早餐、午市、晚市等时段聚合的订单表现", "array", source_tool="analyze_time_patterns", item_schema={"key": "时段代码", "label": "时段中文名称", "order_count": "时段订单数", "revenue": "时段营收/元", "revenue_share": "时段营收占比", "average_order_value": "时段客单价/元"}),
    _m("metrics.time_patterns.peak_daypart", "峰值时段代码", "样本营收最高的时段代码", "string", source_tool="analyze_time_patterns"),
    _m("metrics.time_patterns.peak_daypart_label", "峰值时段", "样本营收最高的时段名称", "string", source_tool="analyze_time_patterns"),
    _m("metrics.time_patterns.trend.status", "营收趋势状态", "前后半段日均营收变化分类", "enum", source_tool="analyze_time_patterns", limitations=("至少需要 6 个有订单营业日",)),
    _m("metrics.time_patterns.trend.change_rate", "营收趋势变化率", "后半段日均营收相对前半段的变化率", "number_or_null", unit="ratio", formula="(recent_average - previous_average) / previous_average", benchmark_required=False, source_tool="analyze_time_patterns", limitations=("样本不足时为空",)),
    _m("metrics.time_patterns.trend.previous_average_revenue", "前半段日均营收", "有订单日期前半段的平均营收", "number_or_null", unit="currency_per_day", source_tool="analyze_time_patterns"),
    _m("metrics.time_patterns.trend.recent_average_revenue", "后半段日均营收", "有订单日期后半段的平均营收", "number_or_null", unit="currency_per_day", source_tool="analyze_time_patterns"),
    _m("metrics.time_patterns.trend.note", "趋势计算说明", "趋势分段和样本要求说明", "string", source_tool="analyze_time_patterns"),
    _m("metrics.time_patterns.anomalies", "异常营业日", "基于中位数和 MAD 识别的异常高低营收日期", "array", source_tool="analyze_time_patterns", limitations=("至少需要 7 个有订单营业日",), item_schema={"date": "日期", "revenue": "当日营收/元", "orders": "订单数", "direction": "high 或 low", "deviation_from_median": "相对中位数偏离比例"}),
    _m("metrics.time_patterns.coverage_note", "时段分析覆盖说明", "无订单日期和营业日口径说明", "string", source_tool="analyze_time_patterns"),

    _m("metrics.menu.items", "菜品矩阵", "以销量中位数和毛利率中位数划分菜品象限", "array", source_tool="analyze_menu_matrix", limitations=("象限是店内样本相对分类，不是行业标准",), item_schema={"item_name": "菜品名称", "category": "品类", "quantity": "销量", "revenue": "实收营收/元", "gross_profit": "毛利额/元", "gross_margin": "毛利率", "quadrant": "star、traffic、profit 或 problem"}),

    _m("metrics.reviews.topics.*", "评论主题提及数", "包含对应关键词的评论条数；不是情感强度", "integer", unit="reviews", source_tool="analyze_review_topics", limitations=("基于固定关键词匹配", "一条评论可命中多个主题")),
    _m("metrics.reviews.review_count", "评论数", "样本评论总数", "integer", unit="reviews", source_tool="analyze_review_topics"),
    _m("metrics.reviews.negative_review_count", "中差评数", "评分不高于 3 分的评论数量", "integer", unit="reviews", formula="count(rating <= 3)", direction="lower_is_better", benchmark_required=True, source_tool="analyze_review_topics"),

    _m("metrics.discounts.segments", "折扣分组", "按标价与实收差额区分原价和折扣订单", "array", source_tool="analyze_discount_profitability", limitations=("没有活动 ID 时不能归因到具体优惠",), item_schema={"key": "regular 或 discounted", "label": "分组名称", "order_count": "订单数", "listed_amount": "菜单标价金额/元", "revenue": "实收营收/元", "average_order_value": "客单价/元", "discount_amount": "折扣金额/元", "discount_rate": "折扣金额占标价比例", "food_cost": "食材成本/元", "contribution_profit": "扣食材后的贡献利润/元", "contribution_margin": "贡献利润率"}),
    _m("metrics.discounts.discounted_order_count", "折扣订单数", "存在标价与实收差额的订单数", "integer", unit="orders", source_tool="analyze_discount_profitability"),
    _m("metrics.discounts.discounted_order_share", "折扣订单占比", "折扣订单数占总订单数比例", "number", unit="ratio", benchmark_required=True, source_tool="analyze_discount_profitability"),
    _m("metrics.discounts.total_discount_amount", "折扣总额", "折扣订单标价减实收的合计", "number", unit="currency", direction="lower_is_better", benchmark_required=True, source_tool="analyze_discount_profitability"),
    _m("metrics.discounts.discounted_contribution_profit", "折扣订单贡献利润", "折扣订单实收扣食材成本后的利润", "number", unit="currency", direction="higher_is_better", benchmark_required=True, source_tool="analyze_discount_profitability", excludes=("平台佣金", "包材", "固定成本")),
    _m("metrics.discounts.discounted_contribution_margin", "折扣订单贡献率", "折扣订单贡献利润占折扣订单实收比例", "number", unit="ratio", direction="higher_is_better", benchmark_required=True, source_tool="analyze_discount_profitability"),
    _m("metrics.discounts.margin_gap_vs_regular", "折扣与原价贡献率差", "折扣订单贡献率减原价订单贡献率", "number_or_null", unit="ratio", formula="discounted_margin - regular_margin", direction="higher_is_better", source_tool="analyze_discount_profitability"),
    _m("metrics.discounts.assumption_note", "折扣识别边界", "折扣识别方法和归因限制", "string", source_tool="analyze_discount_profitability"),

    _m("metrics.survival.observed_days", "财务样本营业日", "生存线计算采用的有订单日期数", "integer", unit="days", source_tool="analyze_survival_line"),
    _m("metrics.survival.observed_revenue", "样本营收", "生存线样本实收营收", "number", unit="currency", source_tool="analyze_survival_line"),
    _m("metrics.survival.observed_food_cost", "样本食材成本", "样本订单菜品成本合计", "number", unit="currency", source_tool="analyze_survival_line"),
    _m("metrics.survival.observed_gross_profit", "样本毛利额", "样本营收减食材成本", "number", unit="currency", source_tool="analyze_survival_line"),
    _m("metrics.survival.observed_gross_margin", "样本毛利率", "样本毛利额占样本营收比例", "number", unit="ratio", benchmark_required=True, source_tool="analyze_survival_line"),
    _m("metrics.survival.average_daily_revenue", "日均营收", "样本营收除以有订单营业日", "number", unit="currency_per_day", benchmark_required=True, source_tool="analyze_survival_line"),
    _m("metrics.survival.projected_monthly_revenue", "月营收投影", "日均营收按 30 天外推", "number", unit="currency", benchmark_required=True, source_tool="analyze_survival_line", limitations=("不是实际财务报表",)),
    _m("metrics.survival.monthly_fixed_cost", "月固定成本", "租金、人工、水电、营销及其他固定成本合计", "number", unit="currency", direction="lower_is_better", source_tool="analyze_survival_line"),
    _m("metrics.survival.break_even_monthly_revenue", "月保本营业额", "覆盖月固定成本所需的月营收", "number", unit="currency", direction="lower_is_better", source_tool="analyze_survival_line"),
    _m("metrics.survival.break_even_daily_revenue", "日保本营业额", "月保本营业额除以 30", "number", unit="currency_per_day", direction="lower_is_better", source_tool="analyze_survival_line"),
    _m("metrics.survival.break_even_daily_orders", "日保本订单数", "按样本客单价覆盖日保本营业额所需订单数", "integer", unit="orders_per_day", direction="lower_is_better", source_tool="analyze_survival_line"),
    _m("metrics.survival.projected_monthly_profit", "月经营利润投影", "月营收投影乘毛利率后减固定成本", "number", unit="currency", direction="higher_is_better", benchmark_required=True, source_tool="analyze_survival_line", limitations=("按样本外推",)),
    _m("metrics.survival.monthly_revenue_gap", "月营收保本缺口", "月营收投影减月保本营业额", "number", unit="currency", direction="higher_is_better", source_tool="analyze_survival_line"),
    _m("metrics.survival.cash_balance", "可用现金", "用户输入的当前可用现金", "number", unit="currency", source_tool="analyze_survival_line"),
    _m("metrics.survival.cash_runway_months", "现金支撑期", "亏损状态下可用现金可覆盖的预计月数", "number_or_null", unit="months", direction="higher_is_better", benchmark_required=True, source_tool="analyze_survival_line"),
    _m("metrics.survival.risk_level", "生存风险等级", "根据利润和现金支撑期划分 stable、watch 或 high", "enum", source_tool="analyze_survival_line"),
    _m("metrics.survival.assumption_note", "生存线假设说明", "月度外推口径和财务边界", "string", source_tool="analyze_survival_line"),
)


SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "channels": ("外卖", "配送", "美团", "饿了么", "渠道", "堂食"),
    "reviews": ("差评", "评论", "评价", "口碑", "投诉"),
    "menu": ("菜品", "菜单", "单品", "毛利", "明星菜"),
    "survival": ("保本", "亏损", "现金", "生存", "利润", "固定成本"),
    "discounts": ("折扣", "优惠", "促销", "满减"),
    "time_patterns": ("时段", "午市", "晚市", "趋势", "异常", "哪天"),
    "revenue": ("营收", "营业额", "订单", "客单"),
}

NORMATIVE_COMPARISON_PHRASES = (
    "偏高", "偏低", "过高", "过低", "较高", "较低",
    "高不高", "低不低", "高吗", "低吗", "是否高", "是否低",
    "好不好", "是否好", "较好", "不好",
    "较差", "很差", "是否差", "差不差",
    "正常", "合理", "健康", "异常", "达标",
    "优秀", "优异", "极差", "糟糕", "良好",
)


def definition_for(path: str) -> MetricDefinition | None:
    exact = next((item for item in METRICS if item.path == path), None)
    if exact:
        return exact
    return next((item for item in METRICS if "*" in item.path and fnmatchcase(path, item.path)), None)


def relevant_sections(question: str) -> set[str]:
    matched = {
        section
        for section, keywords in SECTION_KEYWORDS.items()
        if any(keyword in question for keyword in keywords)
    }
    return matched


def annotate_metric(path: str, value: Any, *, include_value: bool) -> dict[str, Any]:
    definition = definition_for(path)
    result: dict[str, Any] = {
        "ref": path,
        "runtime_type": "null" if value is None else type(value).__name__,
    }
    if definition:
        result.update(definition.context())
        result["ref"] = path
        result.pop("path", None)
    if include_value:
        result["value"] = value
    return result


def metric_catalog(
    metrics: dict[str, Any], *, question: str = "", limit: int = 200
) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    selected = relevant_sections(question)

    def visit(value: Any, path: str) -> None:
        if len(catalog) >= limit:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if not str(key).startswith("_"):
                    visit(child, f"{path}.{key}")
            return
        catalog.append(annotate_metric(path, value, include_value=False))

    for section, value in metrics.items():
        if not section.startswith("_") and (not selected or section in selected):
            visit(value, f"metrics.{section}")
    return catalog


def metric_snapshot(
    metrics: dict[str, Any], *, question: str, limit: int = 120
) -> list[dict[str, Any]]:
    snapshot: list[dict[str, Any]] = []
    selected = relevant_sections(question)

    def visit(value: Any, path: str) -> None:
        if len(snapshot) >= limit:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if not str(key).startswith("_"):
                    visit(child, f"{path}.{key}")
            return
        if not isinstance(value, list):
            snapshot.append(annotate_metric(path, value, include_value=True))

    for section, value in metrics.items():
        if not section.startswith("_") and (not selected or section in selected):
            visit(value, f"metrics.{section}")
    return snapshot


def metric_evidence(
    metrics: dict[str, Any], *, sections: set[str] | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    useful_arrays = {
        "metrics.channels.channels",
        "metrics.menu.items",
        "metrics.time_patterns.anomalies",
    }

    def visit(value: Any, path: str) -> None:
        if len(evidence) >= limit:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if not str(key).startswith("_"):
                    visit(child, f"{path}.{key}")
            return
        if isinstance(value, list) and (path not in useful_arrays or not value):
            return
        annotated = annotate_metric(path, value, include_value=True)
        keep = {
            "ref",
            "label",
            "unit",
            "value",
        }
        evidence.append({key: value for key, value in annotated.items() if key in keep})

    for section, value in metrics.items():
        if not section.startswith("_") and (not sections or section in sections):
            visit(value, f"metrics.{section}")
    return evidence


def definitions_for_sections(
    sections: set[str], *, compact: bool = False
) -> list[dict[str, Any]]:
    definitions = [
        item
        for item in METRICS
        if not sections or item.path.split(".")[1] in sections
    ]
    if not compact:
        return [item.context() for item in definitions]
    keys = {
        "path",
        "label",
        "description",
        "value_type",
        "unit",
        "formula",
        "benchmark_required",
        "limitations",
        "item_schema",
    }
    return [
        {key: value for key, value in item.context().items() if key in keys}
        for item in definitions
    ]


def data_resource_context(metrics: dict[str, Any], *, question: str) -> dict[str, Any]:
    selected = relevant_sections(question)
    definitions = [
        item
        for item in METRICS
        if not selected or item.path.split(".")[1] in selected
    ]
    persisted_resources = (
        metrics.get("_data_resources")
        if isinstance(metrics.get("_data_resources"), dict)
        else {}
    )
    targets = metrics.get("_targets") if isinstance(metrics.get("_targets"), dict) else persisted_resources.get("targets", {})
    benchmarks = metrics.get("_benchmarks") if isinstance(metrics.get("_benchmarks"), dict) else persisted_resources.get("benchmarks", {})
    if not isinstance(targets, dict):
        targets = {}
    if not isinstance(benchmarks, dict):
        benchmarks = {}
    required = [item.path for item in definitions if item.benchmark_required]
    available_reference_paths = set(targets) | set(benchmarks)
    daily = metrics.get("revenue", {}).get("daily_revenue", []) if isinstance(metrics.get("revenue"), dict) else []
    coverage = {
        "date_start": daily[0].get("date") if daily and isinstance(daily[0], dict) else None,
        "date_end": daily[-1].get("date") if daily and isinstance(daily[-1], dict) else None,
        "order_count": metrics.get("revenue", {}).get("order_count") if isinstance(metrics.get("revenue"), dict) else None,
        "review_count": metrics.get("reviews", {}).get("review_count") if isinstance(metrics.get("reviews"), dict) else None,
        "observed_days": metrics.get("time_patterns", {}).get("observed_days") if isinstance(metrics.get("time_patterns"), dict) else None,
    }
    return {
        "coverage": coverage,
        "targets": targets,
        "target_evidence": [
            {"ref": f"targets.{path}", "metric_ref": path, "value": value}
            for path, value in targets.items()
        ],
        "benchmarks": benchmarks,
        "benchmark_status": {
            "required_for": required,
            "available_for": sorted(available_reference_paths),
            "missing_for": [path for path in required if path not in available_reference_paths],
            "rule": "Without a saved target or benchmark, describe the value and composition but do not call it high, low, good, bad, normal, or abnormal.",
        },
        "causal_limit": "Metrics are descriptive unless a definition explicitly identifies an experimental or longitudinal comparison. Do not claim causation from correlation or composition alone.",
    }


def format_value(path: str, value: Any) -> str:
    definition = definition_for(path)
    if isinstance(value, (dict, list)):
        return "已保存的明细数据"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        unit = definition.unit if definition else "none"
        if unit == "ratio":
            return f"{float(value) * 100:.2f}%"
        if unit in {"currency", "currency_per_day", "currency_per_order"}:
            return f"{float(value):.2f}元"
        if unit in {"orders", "days", "reviews", "orders_per_day"}:
            return str(int(value))
    return str(value)


def metric_label(path: str) -> str:
    definition = definition_for(path)
    return definition.label if definition else path


def required_reference_for_question(
    question: str, metrics: dict[str, Any]
) -> str | None:
    candidates = sorted(
        (
            item
            for item in METRICS
            if "*" not in item.path
            and len(item.label) >= 3
            and item.label in question
            and _path_exists(metrics, item.path)
        ),
        key=lambda item: len(item.label),
        reverse=True,
    )
    return candidates[0].path if candidates else None


def answer_requires_benchmark_disclaimer(
    question: str, references: list[str], metrics: dict[str, Any]
) -> bool:
    if not question_requests_normative_comparison(question):
        return False
    benchmark_context = data_resource_context(metrics, question=question)["benchmark_status"]
    available = set(benchmark_context["available_for"])
    return any(
        (definition := definition_for(reference)) is not None
        and definition.benchmark_required
        and reference not in available
        for reference in references
    )


def question_requests_normative_comparison(question: str) -> bool:
    return any(phrase in question for phrase in NORMATIVE_COMPARISON_PHRASES)


def _path_exists(metrics: dict[str, Any], reference: str) -> bool:
    current: Any = metrics
    for part in reference.removeprefix("metrics.").split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False
    return True
