from pathlib import Path

import pandas as pd

from app.tools.break_even_tool import calculate_break_even
from app.tools.menu_tool import analyze_menu_matrix
from app.tools.revenue_tool import analyze_revenue
from app.tools.review_tool import analyze_review_topics
from app.tools.survival_tool import analyze_survival_line
from app.tools.channel_tool import analyze_channel_profitability
from app.tools.time_pattern_tool import analyze_time_patterns
from app.tools.discount_tool import analyze_discount_profitability

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data"


def test_break_even_calculates_daily_revenue_and_orders():
    result = calculate_break_even(
        monthly_rent=18000,
        monthly_labor=24000,
        monthly_utilities=3000,
        monthly_misc=3000,
        gross_margin=0.6,
        avg_order_value=24,
    )

    assert result["daily_fixed_cost"] == 1600
    assert result["break_even_daily_revenue"] == 2666.67
    assert result["break_even_daily_orders"] == 112


def test_revenue_analysis_calculates_core_metrics_from_orders_csv():
    orders = pd.read_csv(SAMPLE_DIR / "orders.csv")

    result = analyze_revenue(orders)

    assert result["total_revenue"] == 336
    assert result["order_count"] == 8
    assert result["avg_order_value"] == 42
    assert result["daily_revenue"] == [
        {"date": "2026-06-01", "revenue": 110.0, "orders": 3},
        {"date": "2026-06-02", "revenue": 88.0, "orders": 2},
        {"date": "2026-06-03", "revenue": 60.0, "orders": 2},
        {"date": "2026-06-04", "revenue": 78.0, "orders": 1},
    ]


def test_menu_matrix_classifies_items_by_sales_and_profit():
    orders = pd.read_csv(SAMPLE_DIR / "orders.csv")
    menu = pd.read_csv(SAMPLE_DIR / "menu_items.csv")

    result = analyze_menu_matrix(orders, menu)
    by_name = {item["item_name"]: item for item in result["items"]}

    assert by_name["招牌拌面"]["quantity"] == 6
    assert by_name["招牌拌面"]["gross_profit"] == 108
    assert by_name["招牌拌面"]["quadrant"] == "star"
    assert by_name["牛肉面"]["quadrant"] == "traffic"
    assert by_name["酸辣粉"]["quadrant"] == "profit"
    assert by_name["小酥肉"]["quadrant"] == "problem"


def test_review_topics_counts_restaurant_problem_keywords():
    reviews = pd.read_csv(SAMPLE_DIR / "reviews.csv")

    result = analyze_review_topics(reviews)

    assert result["topics"]["味道"] == 2
    assert result["topics"]["配送"] == 1
    assert result["topics"]["包装"] == 1
    assert result["topics"]["出餐慢"] == 1
    assert result["negative_review_count"] == 2


def test_survival_line_uses_observed_margin_and_cost_assumptions():
    orders = pd.read_csv(SAMPLE_DIR / "orders.csv")
    menu = pd.read_csv(SAMPLE_DIR / "menu_items.csv")

    result = analyze_survival_line(
        orders,
        menu,
        {
            "monthly_rent": 18000,
            "monthly_labor": 24000,
            "monthly_utilities": 3000,
            "monthly_marketing": 2000,
            "other_fixed_costs": 3000,
            "cash_balance": 120000,
        },
    )

    assert result["observed_food_cost"] == 118
    assert result["observed_gross_profit"] == 218
    assert result["observed_gross_margin"] == 0.6488
    assert result["observed_days"] == 4
    assert result["projected_monthly_revenue"] == 2520
    assert result["monthly_fixed_cost"] == 50000
    assert result["break_even_daily_orders"] == 62
    assert result["projected_monthly_profit"] == -48365
    assert result["cash_runway_months"] == 2.5
    assert result["risk_level"] == "high"


def test_channel_profitability_deducts_delivery_commission_and_packaging():
    orders = pd.read_csv(SAMPLE_DIR / "orders.csv")
    menu = pd.read_csv(SAMPLE_DIR / "menu_items.csv")

    result = analyze_channel_profitability(
        orders,
        menu,
        {"delivery_commission_rate": 0.2, "delivery_packaging_per_order": 1.5},
    )
    by_channel = {item["channel"]: item for item in result["channels"]}

    assert by_channel["dine_in"]["revenue"] == 224
    assert by_channel["dine_in"]["platform_fee"] == 0
    assert by_channel["dine_in"]["contribution_profit"] == 150
    assert by_channel["delivery"]["revenue"] == 112
    assert by_channel["delivery"]["platform_fee"] == 22.4
    assert by_channel["delivery"]["packaging_cost"] == 4.5
    assert by_channel["delivery"]["contribution_profit"] == 41.1
    assert by_channel["delivery"]["contribution_margin"] == 0.367
    assert result["delivery_contribution_profit"] == 41.1


def test_time_patterns_split_dayparts_without_overstating_short_trend():
    orders = pd.read_csv(SAMPLE_DIR / "orders.csv")

    result = analyze_time_patterns(orders)
    by_period = {item["key"]: item for item in result["dayparts"]}

    assert by_period["lunch"]["revenue"] == 224
    assert by_period["lunch"]["order_count"] == 5
    assert by_period["dinner"]["revenue"] == 112
    assert result["peak_daypart"] == "lunch"
    assert result["trend"]["status"] == "insufficient_data"
    assert result["anomalies"] == []


def test_time_patterns_detect_decline_and_unusually_low_day():
    orders = pd.DataFrame(
        {
            "order_id": [f"O-{index}" for index in range(8)],
            "order_time": pd.date_range("2026-07-01 12:00:00", periods=8, freq="D"),
            "channel": ["dine_in"] * 8,
            "item_name": ["测试菜"] * 8,
            "quantity": [1] * 8,
            "actual_amount": [100, 102, 98, 101, 72, 70, 15, 68],
        }
    )

    result = analyze_time_patterns(orders)

    assert result["trend"]["status"] == "declining"
    assert result["trend"]["change_rate"] < -0.4
    assert result["anomalies"] == [
        {
            "date": "2026-07-07",
            "revenue": 15.0,
            "orders": 1,
            "direction": "low",
            "deviation_from_median": -0.8235,
        }
    ]


def test_discount_profitability_compares_listed_and_actual_amounts():
    orders = pd.DataFrame(
        {
            "order_id": ["O-1", "O-2"],
            "order_time": ["2026-07-01 12:00:00", "2026-07-01 18:00:00"],
            "channel": ["dine_in", "delivery"],
            "item_name": ["测试菜", "测试菜"],
            "quantity": [1, 2],
            "actual_amount": [20, 30],
        }
    )
    menu = pd.DataFrame(
        {
            "item_name": ["测试菜"],
            "category": ["主食"],
            "sale_price": [20],
            "unit_cost": [8],
        }
    )

    result = analyze_discount_profitability(orders, menu)
    by_segment = {item["key"]: item for item in result["segments"]}

    assert result["discounted_order_count"] == 1
    assert result["discounted_order_share"] == 0.5
    assert result["total_discount_amount"] == 10
    assert by_segment["regular"]["contribution_margin"] == 0.6
    assert by_segment["discounted"]["contribution_profit"] == 14
    assert by_segment["discounted"]["contribution_margin"] == 0.4667
    assert result["margin_gap_vs_regular"] == -0.1333
