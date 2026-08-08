from __future__ import annotations

import math
from typing import Any

import pandas as pd

from app.services.data_cleaning_service import clean_menu_frame, clean_orders_frame


def analyze_survival_line(
    orders: pd.DataFrame,
    menu: pd.DataFrame,
    assumptions: dict[str, Any],
) -> dict[str, Any]:
    clean_orders = clean_orders_frame(orders)
    clean_menu = clean_menu_frame(menu)
    merged = clean_orders.merge(
        clean_menu[["item_name", "unit_cost"]], on="item_name", how="left"
    )
    if merged["unit_cost"].isna().any():
        raise ValueError("menu cost is missing for one or more ordered items")

    total_revenue = float(merged["actual_amount"].sum())
    if total_revenue <= 0:
        raise ValueError("total revenue must be positive for survival analysis")
    food_cost = float((merged["quantity"] * merged["unit_cost"]).sum())
    gross_profit = total_revenue - food_cost
    gross_margin = gross_profit / total_revenue
    if gross_margin <= 0:
        raise ValueError("observed gross margin must be positive for break-even analysis")

    observed_days = int(clean_orders["order_time"].dt.date.nunique())
    if observed_days <= 0:
        raise ValueError("at least one operating day is required")
    average_daily_revenue = total_revenue / observed_days
    projected_monthly_revenue = average_daily_revenue * 30
    monthly_fixed_cost = sum(
        float(assumptions.get(field, 0) or 0)
        for field in (
            "monthly_rent",
            "monthly_labor",
            "monthly_utilities",
            "monthly_marketing",
            "other_fixed_costs",
        )
    )
    break_even_monthly_revenue = monthly_fixed_cost / gross_margin
    break_even_daily_revenue = break_even_monthly_revenue / 30
    average_order_value = total_revenue / int(clean_orders["order_id"].nunique())
    break_even_daily_orders = math.ceil(break_even_daily_revenue / average_order_value)
    projected_monthly_profit = projected_monthly_revenue * gross_margin - monthly_fixed_cost
    monthly_revenue_gap = projected_monthly_revenue - break_even_monthly_revenue
    cash_balance = float(assumptions.get("cash_balance", 0) or 0)
    cash_runway_months = (
        None
        if projected_monthly_profit >= 0
        else round(cash_balance / abs(projected_monthly_profit), 1)
    )
    risk_level = (
        "stable"
        if projected_monthly_profit >= 0
        else "high"
        if cash_runway_months is not None and cash_runway_months < 3
        else "watch"
    )

    return {
        "observed_days": observed_days,
        "observed_revenue": round(total_revenue, 2),
        "observed_food_cost": round(food_cost, 2),
        "observed_gross_profit": round(gross_profit, 2),
        "observed_gross_margin": round(gross_margin, 4),
        "average_daily_revenue": round(average_daily_revenue, 2),
        "projected_monthly_revenue": round(projected_monthly_revenue, 2),
        "monthly_fixed_cost": round(monthly_fixed_cost, 2),
        "break_even_monthly_revenue": round(break_even_monthly_revenue, 2),
        "break_even_daily_revenue": round(break_even_daily_revenue, 2),
        "break_even_daily_orders": break_even_daily_orders,
        "projected_monthly_profit": round(projected_monthly_profit, 2),
        "monthly_revenue_gap": round(monthly_revenue_gap, 2),
        "cash_balance": round(cash_balance, 2),
        "cash_runway_months": cash_runway_months,
        "risk_level": risk_level,
        "assumption_note": "月度结果按样本日均营收外推 30 天，不代表实际财务报表。",
    }
