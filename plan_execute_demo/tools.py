from __future__ import annotations

from collections import defaultdict
from typing import Any


def analyze_revenue(orders: list[dict[str, str]], _: list[dict[str, str]]) -> dict[str, Any]:
    revenue = sum(float(row["actual_amount"]) for row in orders)
    order_ids = {row["order_id"] for row in orders}
    return {
        "total_revenue": round(revenue, 2),
        "order_count": len(order_ids),
        "avg_order_value": round(revenue / len(order_ids), 2),
    }


def analyze_menu(orders: list[dict[str, str]], menu: list[dict[str, str]]) -> dict[str, Any]:
    costs = {row["item_name"]: float(row["unit_cost"]) for row in menu}
    sales: dict[str, dict[str, float]] = defaultdict(
        lambda: {"quantity": 0.0, "revenue": 0.0, "cost": 0.0}
    )
    for order in orders:
        item = order["item_name"]
        quantity = float(order["quantity"])
        sales[item]["quantity"] += quantity
        sales[item]["revenue"] += float(order["actual_amount"])
        sales[item]["cost"] += quantity * costs[item]

    rows = []
    for item, value in sales.items():
        gross_profit = value["revenue"] - value["cost"]
        rows.append(
            {
                "item_name": item,
                "quantity": int(value["quantity"]),
                "revenue": round(value["revenue"], 2),
                "gross_margin": round(gross_profit / value["revenue"], 4),
            }
        )
    rows.sort(key=lambda row: row["revenue"], reverse=True)
    return {"items": rows}


def analyze_survival(orders: list[dict[str, str]], menu: list[dict[str, str]]) -> dict[str, Any]:
    costs = {row["item_name"]: float(row["unit_cost"]) for row in menu}
    revenue = sum(float(row["actual_amount"]) for row in orders)
    food_cost = sum(
        float(row["quantity"]) * costs[row["item_name"]] for row in orders
    )
    gross_margin = (revenue - food_cost) / revenue
    monthly_fixed_cost = 50_000.0
    break_even_monthly_revenue = monthly_fixed_cost / gross_margin
    return {
        "observed_gross_margin": round(gross_margin, 4),
        "monthly_fixed_cost": monthly_fixed_cost,
        "break_even_monthly_revenue": round(break_even_monthly_revenue, 2),
        "assumption": "固定成本采用演示假设 50,000 元/月",
    }
