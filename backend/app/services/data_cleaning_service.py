import pandas as pd


def clean_orders_frame(orders: pd.DataFrame) -> pd.DataFrame:
    cleaned = orders.copy()
    cleaned["order_time"] = pd.to_datetime(cleaned["order_time"])
    cleaned["quantity"] = pd.to_numeric(cleaned["quantity"])
    cleaned["actual_amount"] = pd.to_numeric(cleaned["actual_amount"])
    return cleaned.drop_duplicates()


def clean_menu_frame(menu: pd.DataFrame) -> pd.DataFrame:
    cleaned = menu.copy()
    cleaned["sale_price"] = pd.to_numeric(cleaned["sale_price"])
    cleaned["unit_cost"] = pd.to_numeric(cleaned["unit_cost"])
    return cleaned.drop_duplicates(subset=["item_name"])


def clean_reviews_frame(reviews: pd.DataFrame) -> pd.DataFrame:
    cleaned = reviews.copy()
    cleaned["review_time"] = pd.to_datetime(cleaned["review_time"])
    cleaned["rating"] = pd.to_numeric(cleaned["rating"])
    cleaned["content"] = cleaned["content"].fillna("").astype(str)
    return cleaned.drop_duplicates()
