import pandas as pd

from app.services.data_cleaning_service import clean_reviews_frame

TOPIC_KEYWORDS = [
    "味道",
    "分量",
    "价格",
    "服务",
    "环境",
    "卫生",
    "出餐慢",
    "配送",
    "漏送",
    "包装",
]


def analyze_review_topics(reviews: pd.DataFrame) -> dict[str, object]:
    clean_reviews = clean_reviews_frame(reviews)
    contents = clean_reviews["content"].tolist()

    topics = {
        keyword: sum(1 for content in contents if keyword in content)
        for keyword in TOPIC_KEYWORDS
    }

    return {
        "topics": topics,
        "review_count": int(len(clean_reviews)),
        "negative_review_count": int((clean_reviews["rating"] <= 3).sum()),
    }
