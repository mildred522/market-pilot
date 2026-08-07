from pathlib import Path

import pandas as pd

from app.tools.break_even_tool import calculate_break_even
from app.tools.menu_tool import analyze_menu_matrix
from app.tools.revenue_tool import analyze_revenue
from app.tools.review_tool import analyze_review_topics

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
