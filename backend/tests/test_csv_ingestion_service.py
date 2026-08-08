from io import BytesIO

import pandas as pd
import pytest

from app.services.csv_ingestion_service import (
    CsvIngestionError,
    mapping_summary,
    prepare_frame,
    read_csv_bytes,
    validate_and_clean,
)


def test_chinese_order_headers_are_suggested_and_cleaned():
    data = "订单号,下单时间,渠道,菜品名称,数量,实收金额\nA1,2026-08-01 12:00,堂食,牛肉面,2,56\n".encode()

    frame = read_csv_bytes(data)
    summary = mapping_summary(frame, "orders")
    prepared = prepare_frame(
        frame,
        file_type="orders",
        mapping=summary["suggested_mapping"],
    )
    cleaned = validate_and_clean(prepared, "orders")

    assert summary["missing_columns"] == []
    assert summary["suggested_mapping"]["actual_amount"] == "实收金额"
    assert cleaned.iloc[0]["quantity"] == 2
    assert cleaned.iloc[0]["actual_amount"] == 56


def test_gb18030_csv_is_supported():
    data = "评论时间,评分,评论内容,渠道\n2026-08-01,2,出餐慢,堂食\n".encode("gb18030")

    frame = read_csv_bytes(data)

    assert list(frame.columns) == ["评论时间", "评分", "评论内容", "渠道"]


def test_mapping_rejects_reused_source_column():
    frame = pd.read_csv(BytesIO(b"a,b\n1,2\n"))

    with pytest.raises(CsvIngestionError, match="不能映射"):
        prepare_frame(
            frame,
            file_type="menu_items",
            mapping={
                "item_name": "a",
                "category": "a",
                "sale_price": "b",
                "unit_cost": "b",
            },
        )


def test_invalid_rating_is_rejected():
    frame = pd.DataFrame(
        [{"review_time": "2026-08-01", "rating": 6, "content": "x", "channel": "堂食"}]
    )

    with pytest.raises(CsvIngestionError, match="1 到 5"):
        validate_and_clean(frame, "reviews")
