from app.agents.state import AgentState


def synthesize(state: AgentState) -> AgentState:
    if state.stage != "operating":
        state.summary = "该项目需要结合投资、租金、商圈和加盟信息判断开店风险。"
        state.actions = ["补充投资预算", "核验商圈客流", "核验加盟品牌真实流水"]
        return state

    revenue = state.tool_results["revenue"]
    menu = state.tool_results["menu"]
    reviews = state.tool_results["reviews"]
    survival = state.tool_results.get("survival")
    channels = state.tool_results.get("channels")
    time_patterns = state.tool_results.get("time_patterns")
    discounts = state.tool_results.get("discounts")
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
    if survival:
        state.summary += (
            f" 按样本外推的月经营利润为 {survival['projected_monthly_profit']} 元，"
            f"日保本营业额为 {survival['break_even_daily_revenue']} 元。"
        )
    state.evidence = [
        f"订单数 {revenue['order_count']}，总营收 {revenue['total_revenue']} 元",
        f"明星菜品：{', '.join(star_items) if star_items else '暂无'}",
        f"问题菜品：{', '.join(problem_items) if problem_items else '暂无'}",
    ]
    if survival:
        state.evidence.extend(
            [
                f"样本实际毛利率 {round(survival['observed_gross_margin'] * 100, 1)}%",
                f"月固定成本 {survival['monthly_fixed_cost']} 元，月保本营业额 {survival['break_even_monthly_revenue']} 元",
            ]
        )
    if channels and channels["delivery_revenue"] > 0:
        state.evidence.append(
            f"外卖营收 {channels['delivery_revenue']} 元，扣食材、佣金和包材后的贡献利润 {channels['delivery_contribution_profit']} 元"
        )
    if time_patterns and time_patterns["peak_daypart_label"]:
        state.evidence.append(
            f"营收最高时段为{time_patterns['peak_daypart_label']}，占样本营收 "
            f"{round(max(item['revenue_share'] for item in time_patterns['dayparts']) * 100, 1)}%"
        )
    if discounts and discounts["discounted_order_count"] > 0:
        state.evidence.append(
            f"折扣订单 {discounts['discounted_order_count']} 单，累计让利 "
            f"{discounts['total_discount_amount']} 元，让利后贡献利润 "
            f"{discounts['discounted_contribution_profit']} 元"
        )
    state.actions = [
        "优先复盘低销量低毛利菜品，判断是否下架或重做定价",
        "针对差评主题检查高峰出餐、包装和配送流程",
        "继续按日跟踪订单数、客单价和菜品毛利贡献",
    ]
    if reviews["negative_review_count"] > 0:
        state.warnings.append("存在中差评，需要优先处理体验问题")
    if survival and survival["risk_level"] != "stable":
        state.warnings.append(
            "当前营收投影低于保本线，需要优先降低固定成本或提升有效订单"
        )
        state.actions.insert(
            0,
            f"将日营收提升至 {survival['break_even_daily_revenue']} 元以上，并连续观察 14 天",
        )
    if survival and survival["risk_level"] == "high":
        state.warnings.append(
            f"现金预计仅可支撑 {survival['cash_runway_months']} 个月，需设置止损节点"
        )
    if channels:
        weak_delivery = [
            item
            for item in channels["channels"]
            if item["channel_type"] == "delivery" and item["contribution_margin"] < 0.25
        ]
        if weak_delivery:
            state.warnings.append("外卖渠道贡献毛利率低于 25%，需检查佣金、满减和包材")
            state.actions.insert(0, "按外卖渠道复核满减后实收、平台佣金和包材成本，暂停负贡献活动")
    if time_patterns:
        trend = time_patterns["trend"]
        if trend["status"] == "declining":
            state.warnings.append(
                f"样本后半段日均营收较前半段下降 {round(abs(trend['change_rate']) * 100, 1)}%"
            )
            state.actions.insert(0, "逐日复盘营收下降是否来自订单数、客单价或重点时段流失")
        low_anomalies = [item for item in time_patterns["anomalies"] if item["direction"] == "low"]
        if low_anomalies:
            state.actions.append("核对异常低营收日的营业时长、缺货、天气、活动和平台曝光记录")
    if discounts and discounts["discounted_order_count"] > 0:
        if discounts["discounted_contribution_profit"] <= 0:
            state.warnings.append("折扣订单扣除食材成本后已无正贡献，促销可能在亏损换单")
            state.actions.insert(0, "立即暂停负贡献折扣，重算满减门槛、折扣率和参与菜品")
        elif (
            discounts["margin_gap_vs_regular"] is not None
            and discounts["margin_gap_vs_regular"] <= -0.1
        ):
            state.warnings.append("折扣订单贡献率较原价订单低 10 个百分点以上")
            state.actions.append("缩小低毛利菜品的优惠范围，按活动前后贡献利润而非订单量复盘")
    return state
