import pandas as pd

from app.services.data_cleaning_service import clean_menu_frame, clean_orders_frame


def analyze_menu_matrix(orders: pd.DataFrame, menu: pd.DataFrame) -> dict[str, object]:
    clean_orders = clean_orders_frame(orders)
    clean_menu = clean_menu_frame(menu)

    item_sales = (
        clean_orders.groupby("item_name", as_index=False)
        .agg(quantity=("quantity", "sum"), revenue=("actual_amount", "sum"))
        .merge(clean_menu, on="item_name", how="left")
    )
    item_sales["cost"] = item_sales["quantity"] * item_sales["unit_cost"]
    item_sales["gross_profit"] = item_sales["revenue"] - item_sales["cost"]
    item_sales["gross_margin"] = item_sales["gross_profit"] / item_sales["revenue"]

    quantity_threshold = item_sales["quantity"].median()
    margin_threshold = item_sales["gross_margin"].median()

    items: list[dict[str, object]] = []
    for row in item_sales.to_dict(orient="records"):
        high_sales = row["quantity"] >= quantity_threshold
        high_margin = row["gross_margin"] >= margin_threshold
        if high_sales and high_margin:
            quadrant = "star"
        elif high_sales and not high_margin:
            quadrant = "traffic"
        elif not high_sales and high_margin:
            quadrant = "profit"
        else:
            quadrant = "problem"

        items.append(
            {
                "item_name": row["item_name"],
                "category": row["category"],
                "quantity": int(row["quantity"]),
                "revenue": round(float(row["revenue"]), 2),
                "gross_profit": round(float(row["gross_profit"]), 2),
                "gross_margin": round(float(row["gross_margin"]), 4),
                "quadrant": quadrant,
            }
        )

    return {"items": items}
