import pandas as pd

from app.tools.menu_tool import analyze_menu_matrix
from app.tools.revenue_tool import analyze_revenue
from app.tools.review_tool import analyze_review_topics


def analyze_operating_metrics(
    orders: pd.DataFrame, menu: pd.DataFrame, reviews: pd.DataFrame
) -> dict[str, object]:
    return {
        "revenue": analyze_revenue(orders),
        "menu": analyze_menu_matrix(orders, menu),
        "reviews": analyze_review_topics(reviews),
    }
