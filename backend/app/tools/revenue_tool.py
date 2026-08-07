import pandas as pd

from app.services.data_cleaning_service import clean_orders_frame


def analyze_revenue(orders: pd.DataFrame) -> dict[str, object]:
    clean_orders = clean_orders_frame(orders)
    clean_orders["date"] = clean_orders["order_time"].dt.strftime("%Y-%m-%d")

    daily = (
        clean_orders.groupby("date", as_index=False)
        .agg(revenue=("actual_amount", "sum"), orders=("order_id", "nunique"))
        .sort_values("date")
    )

    return {
        "total_revenue": round(float(clean_orders["actual_amount"].sum()), 2),
        "order_count": int(clean_orders["order_id"].nunique()),
        "avg_order_value": round(float(clean_orders["actual_amount"].sum()) / len(clean_orders), 2),
        "daily_revenue": [
            {
                "date": row["date"],
                "revenue": round(float(row["revenue"]), 2),
                "orders": int(row["orders"]),
            }
            for row in daily.to_dict(orient="records")
        ],
    }
