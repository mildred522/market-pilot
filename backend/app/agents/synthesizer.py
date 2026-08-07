from app.agents.state import AgentState


def synthesize(state: AgentState) -> AgentState:
    if state.stage != "operating":
        state.summary = "该项目需要结合投资、租金、商圈和加盟信息判断开店风险。"
        state.actions = ["补充投资预算", "核验商圈客流", "核验加盟品牌真实流水"]
        return state

    revenue = state.tool_results["revenue"]
    menu = state.tool_results["menu"]
    reviews = state.tool_results["reviews"]
    star_items = [
        item["item_name"] for item in menu["items"] if item["quadrant"] == "star"
    ]
    problem_items = [
        item["item_name"] for item in menu["items"] if item["quadrant"] == "problem"
    ]

    state.summary = (
        f"当前样本期营收 {revenue['total_revenue']} 元，"
        f"客单价 {revenue['avg_order_value']} 元；"
        f"差评或中评共 {reviews['negative_review_count']} 条。"
    )
    state.evidence = [
        f"订单数 {revenue['order_count']}，总营收 {revenue['total_revenue']} 元",
        f"明星菜品：{', '.join(star_items) if star_items else '暂无'}",
        f"问题菜品：{', '.join(problem_items) if problem_items else '暂无'}",
    ]
    state.actions = [
        "优先复盘低销量低毛利菜品，判断是否下架或重做定价",
        "针对差评主题检查高峰出餐、包装和配送流程",
        "继续按日跟踪订单数、客单价和菜品毛利贡献",
    ]
    if reviews["negative_review_count"] > 0:
        state.warnings.append("存在中差评，需要优先处理体验问题")
    return state
