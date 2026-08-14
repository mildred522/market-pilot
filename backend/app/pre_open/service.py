from app.pre_open.contracts import (
    PreOpenAssessmentInput,
    PreOpenAssessmentResult,
    PreOpenMetrics,
)


class PreOpenAssessmentService:
    def analyze(self, value: PreOpenAssessmentInput) -> PreOpenAssessmentResult:
        estimated_daily_revenue = round(
            value.expected_daily_orders * value.expected_avg_order_value, 2
        )
        estimated_daily_gross_profit = round(
            estimated_daily_revenue * value.expected_gross_margin, 2
        )
        daily_rent = round(value.monthly_rent / 30, 2)

        risks: list[str] = []
        if value.debt_amount > value.own_capital * 0.6:
            risks.append("负债占比较高，现金流抗压能力偏弱")
        if value.competitor_count >= 6:
            risks.append("周边竞品密度较高，需要明确差异化")
        if value.is_franchise and value.franchise_fee > 50000:
            risks.append("加盟投入较高，需要核验真实门店流水")
        if estimated_daily_gross_profit <= daily_rent:
            risks.append("预估日毛利不足以覆盖日均房租")

        metrics = PreOpenMetrics(
            estimated_daily_revenue=estimated_daily_revenue,
            estimated_daily_gross_profit=estimated_daily_gross_profit,
            daily_rent=daily_rent,
        )
        return PreOpenAssessmentResult(
            summary="当前项目需要重点核验租金、竞品密度和加盟投入是否匹配预估流水。",
            metrics=metrics,
            evidence=(
                f"预计日营收 {estimated_daily_revenue} 元",
                f"预计日毛利 {estimated_daily_gross_profit} 元",
                f"日均房租 {daily_rent} 元",
            ),
            risks=tuple(risks),
            actions=(
                "开店前连续 3 天蹲点记录午市和晚市客流",
                "向至少 2 家同品类竞品估算订单量和价格带",
                "核验加盟品牌直营店流水和老加盟商闭店情况",
            ),
            limitations=(
                "输入值为用户预估，并非真实经营数据",
                "本结果用于缩小核验范围，不构成开店成功保证",
            ),
        )
