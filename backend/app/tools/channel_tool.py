from __future__ import annotations

from typing import Any

import pandas as pd

from app.services.data_cleaning_service import clean_menu_frame, clean_orders_frame


DELIVERY_MARKERS = ("delivery", "外卖", "美团", "饿了么")


def analyze_channel_profitability(
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
        raise ValueError("menu cost is missing for channel analysis")
    merged["food_cost"] = merged["quantity"] * merged["unit_cost"]
    total_revenue = float(merged["actual_amount"].sum())
    commission_rate = float(assumptions.get("delivery_commission_rate", 0) or 0)
    packaging_per_order = float(assumptions.get("delivery_packaging_per_order", 0) or 0)

    channels: list[dict[str, Any]] = []
    for channel, group in merged.groupby("channel", sort=True):
        channel_name = str(channel)
        is_delivery = _is_delivery(channel_name)
        revenue = float(group["actual_amount"].sum())
        order_count = int(group["order_id"].nunique())
        food_cost = float(group["food_cost"].sum())
        platform_fee = revenue * commission_rate if is_delivery else 0.0
        packaging_cost = order_count * packaging_per_order if is_delivery else 0.0
        contribution_profit = revenue - food_cost - platform_fee - packaging_cost
        channels.append(
            {
                "channel": channel_name,
                "channel_type": "delivery" if is_delivery else "direct",
                "order_count": order_count,
                "revenue": round(revenue, 2),
                "revenue_share": round(revenue / total_revenue, 4) if total_revenue else 0.0,
                "average_order_value": round(revenue / order_count, 2) if order_count else 0.0,
                "food_cost": round(food_cost, 2),
                "platform_fee": round(platform_fee, 2),
                "packaging_cost": round(packaging_cost, 2),
                "contribution_profit": round(contribution_profit, 2),
                "contribution_margin": round(contribution_profit / revenue, 4) if revenue else 0.0,
            }
        )
    channels.sort(key=lambda item: (-item["revenue"], item["channel"]))
    delivery_channels = [item for item in channels if item["channel_type"] == "delivery"]
    delivery_revenue = round(sum(item["revenue"] for item in delivery_channels), 2)
    delivery_food_cost = round(sum(item["food_cost"] for item in delivery_channels), 2)
    delivery_platform_fee = round(
        sum(item["platform_fee"] for item in delivery_channels), 2
    )
    delivery_packaging_cost = round(
        sum(item["packaging_cost"] for item in delivery_channels), 2
    )
    delivery_contribution_profit = round(
        sum(item["contribution_profit"] for item in delivery_channels), 2
    )
    return {
        "channels": channels,
        "delivery_commission_rate": commission_rate,
        "delivery_packaging_per_order": packaging_per_order,
        "delivery_revenue": delivery_revenue,
        "delivery_revenue_share": (
            round(delivery_revenue / total_revenue, 4) if total_revenue else 0.0
        ),
        "delivery_food_cost": delivery_food_cost,
        "delivery_platform_fee": delivery_platform_fee,
        "delivery_packaging_cost": delivery_packaging_cost,
        "delivery_contribution_profit": delivery_contribution_profit,
        "delivery_contribution_margin": (
            round(delivery_contribution_profit / delivery_revenue, 4)
            if delivery_revenue
            else 0.0
        ),
        "assumption_note": "渠道贡献利润未分摊房租、人工等固定成本。",
    }


def _is_delivery(channel: str) -> bool:
    normalized = channel.strip().lower()
    return any(marker in normalized for marker in DELIVERY_MARKERS)
