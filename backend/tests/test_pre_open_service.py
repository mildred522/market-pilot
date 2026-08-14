from app.pre_open.contracts import PreOpenAssessmentInput
from app.pre_open.service import PreOpenAssessmentService


def test_pre_open_service_returns_typed_metrics_risks_and_limitations():
    result = PreOpenAssessmentService().analyze(
        PreOpenAssessmentInput(
            monthly_rent=18000,
            total_investment=280000,
            own_capital=150000,
            debt_amount=130000,
            expected_daily_orders=90,
            expected_avg_order_value=24,
            expected_gross_margin=0.62,
            is_franchise=True,
            franchise_fee=68000,
            competitor_count=8,
        )
    )

    assert result.metrics.estimated_daily_revenue == 2160
    assert result.metrics.estimated_daily_gross_profit == 1339.2
    assert result.metrics.daily_rent == 600
    assert len(result.evidence) == 3
    assert "负债占比较高，现金流抗压能力偏弱" in result.risks
    assert "周边竞品密度较高，需要明确差异化" in result.risks
    assert "加盟投入较高，需要核验真实门店流水" in result.risks
    assert result.actions
    assert "输入值为用户预估，并非真实经营数据" in result.limitations


def test_pre_open_service_flags_when_daily_gross_profit_does_not_cover_rent():
    result = PreOpenAssessmentService().analyze(
        PreOpenAssessmentInput(
            monthly_rent=30000,
            total_investment=100000,
            own_capital=100000,
            debt_amount=0,
            expected_daily_orders=20,
            expected_avg_order_value=20,
            expected_gross_margin=0.5,
            is_franchise=False,
            franchise_fee=0,
            competitor_count=1,
        )
    )

    assert "预估日毛利不足以覆盖日均房租" in result.risks
