from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from app.agent_runtime.contracts import OperatingWorkflowName
from app.agent_runtime.tools import (
    OPERATING_TOOLS,
    OperatingToolContext,
    available_tool_specs,
)


@dataclass(frozen=True)
class WorkflowDimension:
    name: str
    description: str
    tools: tuple[str, ...]
    markers: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowDefinition:
    name: OperatingWorkflowName
    description: str
    use_when: tuple[str, ...]
    default_dimensions: tuple[str, ...]
    dimensions: tuple[WorkflowDimension, ...]
    limitations: tuple[str, ...]

    def planner_card(self, available_tools: set[str]) -> dict[str, object]:
        available_dimensions = [
            item
            for item in self.dimensions
            if all(tool in available_tools for tool in item.tools)
        ]
        available_names = {item.name for item in available_dimensions}
        return {
            "name": self.name.value,
            "description": self.description,
            "use_when": list(self.use_when),
            "default_dimensions": [
                item for item in self.default_dimensions if item in available_names
            ],
            "dimensions": [
                {"name": item.name, "description": item.description}
                for item in available_dimensions
            ],
            "unavailable_dimensions": [
                item.name for item in self.dimensions if item.name not in available_names
            ],
            "limitations": list(self.limitations),
        }


_WORKFLOWS = {
    OperatingWorkflowName.REVENUE_TREND: WorkflowDefinition(
        name=OperatingWorkflowName.REVENUE_TREND,
        description="分析营收规模、订单量、客单价和时间趋势。",
        use_when=("营收", "营业额", "订单", "客单价", "最近下降", "趋势"),
        default_dimensions=("revenue",),
        dimensions=(
            WorkflowDimension(
                "revenue", "核算营收、订单量和客单价。",
                ("analyze_revenue",), ("营收", "营业额", "订单", "客单价"),
            ),
            WorkflowDimension(
                "trend", "比较时段、前后阶段和异常日期。",
                ("analyze_time_patterns",), ("趋势", "最近", "时段", "高峰", "异常"),
            ),
            WorkflowDimension(
                "channel", "拆分堂食和外卖渠道表现。",
                ("analyze_channel_profitability",), ("外卖", "堂食", "渠道"),
            ),
        ),
        limitations=("不能仅凭短期相关性判断下降原因",),
    ),
    OperatingWorkflowName.PROFIT_DIAGNOSIS: WorkflowDefinition(
        name=OperatingWorkflowName.PROFIT_DIAGNOSIS,
        description="诊断亏损、利润下降、保本压力和现金风险。",
        use_when=("利润", "不赚钱", "亏损", "保本", "现金", "成本", "生存"),
        default_dimensions=("survival",),
        dimensions=(
            WorkflowDimension(
                "survival", "核算利润投影、保本线和现金支撑。",
                ("analyze_survival_line",), ("利润", "亏损", "保本", "现金", "成本"),
            ),
            WorkflowDimension(
                "trend", "判断利润压力是否伴随营收时序变化。",
                ("analyze_time_patterns",), ("最近", "下降", "趋势", "越来越"),
            ),
            WorkflowDimension(
                "channel", "检查渠道佣金和贡献利润。",
                ("analyze_channel_profitability",), ("外卖", "堂食", "渠道", "佣金", "包材"),
            ),
            WorkflowDimension(
                "promotion", "检查折扣订单是否侵蚀利润。",
                ("analyze_discount_profitability",), ("折扣", "优惠", "促销", "满减"),
            ),
            WorkflowDimension(
                "product", "检查菜品销量和毛利结构。",
                ("analyze_menu_matrix",), ("菜品", "菜单", "产品", "毛利"),
            ),
        ),
        limitations=("利润投影基于上传样本和成本假设",),
    ),
    OperatingWorkflowName.MENU_OPTIMIZATION: WorkflowDefinition(
        name=OperatingWorkflowName.MENU_OPTIMIZATION,
        description="分析菜品去留、销量毛利、新品和菜单结构。",
        use_when=("菜品", "菜单", "下架", "新品", "爆款", "毛利"),
        default_dimensions=("product",),
        dimensions=(
            WorkflowDimension(
                "product", "分析菜品销量、毛利和经营象限。",
                ("analyze_menu_matrix",), ("菜品", "菜单", "下架", "新品", "毛利"),
            ),
            WorkflowDimension(
                "customer", "结合顾客评论检查菜品体验。",
                ("analyze_review_topics",), ("顾客", "评论", "差评", "口味"),
            ),
            WorkflowDimension(
                "promotion", "检查菜品表现是否受到折扣影响。",
                ("analyze_discount_profitability",), ("折扣", "优惠", "促销"),
            ),
            WorkflowDimension(
                "revenue", "补充整体营收和订单规模。",
                ("analyze_revenue",), ("营收", "订单", "客单"),
            ),
        ),
        limitations=("店内象限不是行业标准，也不能推断未售新品需求",),
    ),
    OperatingWorkflowName.CUSTOMER_EXPERIENCE: WorkflowDefinition(
        name=OperatingWorkflowName.CUSTOMER_EXPERIENCE,
        description="分析差评、顾客反馈和服务体验问题。",
        use_when=("评论", "差评", "顾客反馈", "体验", "服务", "口味"),
        default_dimensions=("customer",),
        dimensions=(
            WorkflowDimension(
                "customer", "统计差评和顾客反馈主题。",
                ("analyze_review_topics",), ("评论", "差评", "顾客", "体验", "服务"),
            ),
            WorkflowDimension(
                "time", "观察体验问题是否与繁忙时段同时出现。",
                ("analyze_time_patterns",), ("时段", "高峰", "午市", "晚市", "集中"),
            ),
            WorkflowDimension(
                "product", "结合菜品销量和毛利结构。",
                ("analyze_menu_matrix",), ("菜品", "菜单", "产品", "口味"),
            ),
        ),
        limitations=("关键词主题不能证明具体问题的因果关系",),
    ),
    OperatingWorkflowName.PROMOTION_CHANNEL: WorkflowDefinition(
        name=OperatingWorkflowName.PROMOTION_CHANNEL,
        description="分析优惠活动、外卖渠道和获客方式的经营贡献。",
        use_when=("促销", "折扣", "优惠", "满减", "外卖", "堂食", "渠道", "佣金"),
        default_dimensions=("promotion", "channel"),
        dimensions=(
            WorkflowDimension(
                "promotion", "比较折扣与原价订单利润。",
                ("analyze_discount_profitability",), ("折扣", "优惠", "促销", "满减"),
            ),
            WorkflowDimension(
                "channel", "比较堂食与外卖贡献。",
                ("analyze_channel_profitability",), ("外卖", "堂食", "渠道", "佣金", "包材"),
            ),
            WorkflowDimension(
                "survival", "评估策略对保本和现金风险的影响。",
                ("analyze_survival_line",), ("利润", "亏损", "保本", "现金"),
            ),
        ),
        limitations=("没有活动 ID 时不能归因到单个营销活动",),
    ),
}

WORKFLOW_REGISTRY = MappingProxyType(_WORKFLOWS)


def available_workflows(context: OperatingToolContext) -> list[WorkflowDefinition]:
    available_inputs = context.available_inputs
    return [
        workflow
        for workflow in WORKFLOW_REGISTRY.values()
        if any(
            all(
                set(OPERATING_TOOLS[tool].required_inputs) <= available_inputs
                for tool in dimension.tools
            )
            for dimension in workflow.dimensions
        )
    ]


def workflow_candidates(
    question: str, context: OperatingToolContext
) -> list[WorkflowDefinition]:
    available = available_workflows(context)
    matched = [
        workflow
        for workflow in available
        if any(marker in question for marker in workflow.use_when)
    ]
    return matched or available


def expand_workflow(
    name: OperatingWorkflowName,
    dimensions: list[str],
    context: OperatingToolContext,
) -> list[str]:
    workflow = WORKFLOW_REGISTRY[name]
    available_tools = {spec.name for spec in available_tool_specs(context)}
    by_name = {item.name: item for item in workflow.dimensions}
    unknown = [item for item in dimensions if item not in by_name]
    if unknown:
        raise ValueError(
            f"unknown dimensions for {name.value}: {', '.join(unknown)}"
        )
    selected = []
    for dimension in dimensions or list(workflow.default_dimensions):
        selected.extend(by_name[dimension].tools)
    return [
        tool
        for tool in dict.fromkeys(selected)
        if tool in available_tools
    ]
