from __future__ import annotations

from typing import Any

import pandas as pd

from app.services.data_cleaning_service import clean_orders_frame


DAYPARTS = (
    ("late_night", "深夜", 0, 5),
    ("breakfast", "早餐", 5, 10),
    ("lunch", "午市", 10, 14),
    ("afternoon", "下午", 14, 17),
    ("dinner", "晚市", 17, 21),
    ("night", "夜宵", 21, 24),
)


def analyze_time_patterns(orders: pd.DataFrame) -> dict[str, Any]:
    clean_orders = clean_orders_frame(orders)
    order_level = (
        clean_orders.groupby("order_id", as_index=False)
        .agg(order_time=("order_time", "min"), revenue=("actual_amount", "sum"))
    )
    order_level["date"] = order_level["order_time"].dt.strftime("%Y-%m-%d")
    order_level["daypart"] = order_level["order_time"].dt.hour.map(_daypart_key)

    total_revenue = float(order_level["revenue"].sum())
    dayparts: list[dict[str, Any]] = []
    for key, label, _, _ in DAYPARTS:
        period = order_level[order_level["daypart"] == key]
        revenue = float(period["revenue"].sum())
        order_count = int(len(period))
        dayparts.append(
            {
                "key": key,
                "label": label,
                "order_count": order_count,
                "revenue": round(revenue, 2),
                "revenue_share": round(revenue / total_revenue, 4) if total_revenue else 0.0,
                "average_order_value": round(revenue / order_count, 2) if order_count else 0.0,
            }
        )

    daily = (
        order_level.groupby("date", as_index=False)
        .agg(revenue=("revenue", "sum"), orders=("order_id", "count"))
        .sort_values("date")
        .reset_index(drop=True)
    )
    trend = _analyze_trend(daily)
    anomalies = _find_anomalies(daily)
    active_periods = [item for item in dayparts if item["order_count"] > 0]
    peak = max(active_periods, key=lambda item: item["revenue"], default=None)

    return {
        "observed_days": int(len(daily)),
        "dayparts": dayparts,
        "peak_daypart": peak["key"] if peak else None,
        "peak_daypart_label": peak["label"] if peak else None,
        "trend": trend,
        "anomalies": anomalies,
        "coverage_note": "趋势仅基于 CSV 中有订单记录的营业日；无订单日期不会自动视为停业或零营收。",
    }


def _daypart_key(hour: int) -> str:
    for key, _, start, end in DAYPARTS:
        if start <= hour < end:
            return key
    return "late_night"


def _analyze_trend(daily: pd.DataFrame) -> dict[str, Any]:
    if len(daily) < 6:
        return {
            "status": "insufficient_data",
            "change_rate": None,
            "previous_average_revenue": None,
            "recent_average_revenue": None,
            "note": "至少需要 6 个有订单营业日，才能比较前后半段趋势。",
        }

    midpoint = len(daily) // 2
    previous_average = float(daily.iloc[:midpoint]["revenue"].mean())
    recent_average = float(daily.iloc[midpoint:]["revenue"].mean())
    change_rate = (
        (recent_average - previous_average) / previous_average
        if previous_average
        else None
    )
    if change_rate is None:
        status = "insufficient_data"
    elif change_rate <= -0.1:
        status = "declining"
    elif change_rate >= 0.1:
        status = "growing"
    else:
        status = "stable"
    return {
        "status": status,
        "change_rate": round(change_rate, 4) if change_rate is not None else None,
        "previous_average_revenue": round(previous_average, 2),
        "recent_average_revenue": round(recent_average, 2),
        "note": "按有订单营业日排序，将样本前半段与后半段的日均营收进行比较。",
    }


def _find_anomalies(daily: pd.DataFrame) -> list[dict[str, Any]]:
    if len(daily) < 7:
        return []
    median = float(daily["revenue"].median())
    absolute_deviation = (daily["revenue"] - median).abs()
    mad = float(absolute_deviation.median())
    anomalies: list[dict[str, Any]] = []
    for row in daily.to_dict(orient="records"):
        revenue = float(row["revenue"])
        if mad > 0:
            score = 0.6745 * (revenue - median) / mad
            is_anomaly = abs(score) >= 2.5
        else:
            score = None
            is_anomaly = median > 0 and abs(revenue - median) / median >= 0.3
        if is_anomaly:
            anomalies.append(
                {
                    "date": row["date"],
                    "revenue": round(revenue, 2),
                    "orders": int(row["orders"]),
                    "direction": "high" if revenue > median else "low",
                    "deviation_from_median": round((revenue - median) / median, 4)
                    if median
                    else None,
                }
            )
    return anomalies
