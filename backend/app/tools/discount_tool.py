from __future__ import annotations

from typing import Any

import pandas as pd

from app.services.data_cleaning_service import clean_menu_frame, clean_orders_frame


def analyze_discount_profitability(
    orders: pd.DataFrame,
    menu: pd.DataFrame,
) -> dict[str, Any]:
    clean_orders = clean_orders_frame(orders)
    clean_menu = clean_menu_frame(menu)
    merged = clean_orders.merge(
        clean_menu[["item_name", "sale_price", "unit_cost"]],
        on="item_name",
        how="left",
    )
    if merged[["sale_price", "unit_cost"]].isna().any().any():
        raise ValueError("menu price or cost is missing for discount analysis")

    merged["listed_amount"] = merged["quantity"] * merged["sale_price"]
    merged["food_cost"] = merged["quantity"] * merged["unit_cost"]
    order_level = (
        merged.groupby("order_id", as_index=False)
        .agg(
            listed_amount=("listed_amount", "sum"),
            actual_amount=("actual_amount", "sum"),
            food_cost=("food_cost", "sum"),
        )
    )
    order_level["discount_amount"] = (
        order_level["listed_amount"] - order_level["actual_amount"]
    ).clip(lower=0)
    order_level["is_discounted"] = order_level["discount_amount"] >= 0.01

    discounted = _segment(order_level[order_level["is_discounted"]], "discounted", "折扣订单")
    regular = _segment(order_level[~order_level["is_discounted"]], "regular", "原价订单")
    return {
        "segments": [regular, discounted],
        "discounted_order_count": discounted["order_count"],
        "discounted_order_share": round(
            discounted["order_count"] / len(order_level), 4
        )
        if len(order_level)
        else 0.0,
        "total_discount_amount": discounted["discount_amount"],
        "discounted_contribution_profit": discounted["contribution_profit"],
        "discounted_contribution_margin": discounted["contribution_margin"],
        "margin_gap_vs_regular": round(
            discounted["contribution_margin"] - regular["contribution_margin"], 4
        )
        if discounted["order_count"] and regular["order_count"]
        else None,
        "assumption_note": "折扣订单由菜单标价与订单实收差额推断；未提供活动 ID 时，不能归因到具体满减或优惠券。",
    }


def _segment(frame: pd.DataFrame, key: str, label: str) -> dict[str, Any]:
    order_count = int(len(frame))
    listed_amount = float(frame["listed_amount"].sum())
    revenue = float(frame["actual_amount"].sum())
    food_cost = float(frame["food_cost"].sum())
    discount_amount = float(frame["discount_amount"].sum())
    contribution_profit = revenue - food_cost
    return {
        "key": key,
        "label": label,
        "order_count": order_count,
        "listed_amount": round(listed_amount, 2),
        "revenue": round(revenue, 2),
        "average_order_value": round(revenue / order_count, 2) if order_count else 0.0,
        "discount_amount": round(discount_amount, 2),
        "discount_rate": round(discount_amount / listed_amount, 4) if listed_amount else 0.0,
        "food_cost": round(food_cost, 2),
        "contribution_profit": round(contribution_profit, 2),
        "contribution_margin": round(contribution_profit / revenue, 4) if revenue else 0.0,
    }
