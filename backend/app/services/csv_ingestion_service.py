from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd


CSV_FILE_TYPES = ("orders", "menu_items", "reviews")

REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "orders": (
        "order_id",
        "order_time",
        "channel",
        "item_name",
        "quantity",
        "actual_amount",
    ),
    "menu_items": ("item_name", "category", "sale_price", "unit_cost"),
    "reviews": ("review_time", "rating", "content", "channel"),
}

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "order_id": ("order_id", "订单号", "订单编号", "订单id", "单号"),
    "order_time": ("order_time", "下单时间", "订单时间", "交易时间", "日期时间"),
    "channel": ("channel", "渠道", "订单渠道", "来源", "平台"),
    "item_name": ("item_name", "菜品名称", "商品名称", "菜名", "商品"),
    "quantity": ("quantity", "数量", "销量", "购买数量", "份数"),
    "actual_amount": ("actual_amount", "实收金额", "订单实收", "实付金额", "销售额", "营业额"),
    "category": ("category", "分类", "菜品分类", "商品分类", "品类"),
    "sale_price": ("sale_price", "售价", "销售价格", "价格", "单价"),
    "unit_cost": ("unit_cost", "单位成本", "成本", "成本价", "食材成本"),
    "review_time": ("review_time", "评论时间", "评价时间", "时间", "日期"),
    "rating": ("rating", "评分", "星级", "评价星级"),
    "content": ("content", "评论内容", "评价内容", "评论", "评价"),
}


class CsvIngestionError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_csv") -> None:
        self.code = code
        super().__init__(message)


def read_csv_bytes(data: bytes) -> pd.DataFrame:
    if not data:
        raise CsvIngestionError("CSV 文件为空", code="empty_csv")
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            frame = pd.read_csv(BytesIO(data), encoding=encoding)
            return _normalize_headers(frame)
        except UnicodeDecodeError as error:
            last_error = error
        except pd.errors.EmptyDataError as error:
            raise CsvIngestionError("CSV 文件没有表头或数据", code="empty_csv") from error
        except pd.errors.ParserError as error:
            raise CsvIngestionError("CSV 格式无法解析，请检查分隔符和引号", code="invalid_csv") from error
    raise CsvIngestionError("CSV 编码不受支持，请使用 UTF-8 或 GB18030", code="unsupported_encoding") from last_error


def read_csv_path(path: Path) -> pd.DataFrame:
    try:
        return read_csv_bytes(path.read_bytes())
    except OSError as error:
        raise CsvIngestionError("已上传文件无法读取", code="file_unavailable") from error


def suggest_mapping(frame: pd.DataFrame, file_type: str) -> dict[str, str]:
    required = _required(file_type)
    normalized_sources = {_key(column): str(column) for column in frame.columns}
    mapping: dict[str, str] = {}
    for standard in required:
        for alias in COLUMN_ALIASES.get(standard, (standard,)):
            source = normalized_sources.get(_key(alias))
            if source is not None:
                mapping[standard] = source
                break
    return mapping


def prepare_frame(
    frame: pd.DataFrame,
    *,
    file_type: str,
    mapping: dict[str, str],
) -> pd.DataFrame:
    required = _required(file_type)
    unknown_targets = sorted(set(mapping) - set(required))
    if unknown_targets:
        raise CsvIngestionError(
            f"字段映射包含未知标准字段：{', '.join(unknown_targets)}",
            code="invalid_mapping",
        )
    missing_targets = [column for column in required if not mapping.get(column)]
    if missing_targets:
        raise CsvIngestionError(
            f"仍需映射字段：{', '.join(missing_targets)}",
            code="missing_columns",
        )
    missing_sources = sorted({source for source in mapping.values() if source not in frame.columns})
    if missing_sources:
        raise CsvIngestionError(
            f"CSV 中不存在映射列：{', '.join(missing_sources)}",
            code="invalid_mapping",
        )
    if len(set(mapping.values())) != len(mapping):
        raise CsvIngestionError("同一个 CSV 列不能映射到多个标准字段", code="invalid_mapping")
    prepared = frame.rename(columns={source: target for target, source in mapping.items()})
    prepared = prepared.loc[:, list(required)].copy()
    if prepared.empty:
        raise CsvIngestionError("CSV 没有可分析的数据行", code="empty_csv")
    return prepared


def validate_and_clean(frame: pd.DataFrame, file_type: str) -> pd.DataFrame:
    try:
        if file_type == "orders":
            frame["order_time"] = pd.to_datetime(frame["order_time"], errors="raise")
            frame["quantity"] = pd.to_numeric(frame["quantity"], errors="raise")
            frame["actual_amount"] = pd.to_numeric(frame["actual_amount"], errors="raise")
            if (frame["quantity"] <= 0).any() or (frame["actual_amount"] < 0).any():
                raise CsvIngestionError("订单数量必须大于 0，实收金额不能为负数")
        elif file_type == "menu_items":
            frame["sale_price"] = pd.to_numeric(frame["sale_price"], errors="raise")
            frame["unit_cost"] = pd.to_numeric(frame["unit_cost"], errors="raise")
            if (frame["sale_price"] <= 0).any() or (frame["unit_cost"] < 0).any():
                raise CsvIngestionError("菜品售价必须大于 0，单位成本不能为负数")
        elif file_type == "reviews":
            frame["review_time"] = pd.to_datetime(frame["review_time"], errors="raise")
            frame["rating"] = pd.to_numeric(frame["rating"], errors="raise")
            if ((frame["rating"] < 1) | (frame["rating"] > 5)).any():
                raise CsvIngestionError("评论评分必须在 1 到 5 之间")
            frame["content"] = frame["content"].fillna("").astype(str)
    except (TypeError, ValueError) as error:
        if isinstance(error, CsvIngestionError):
            raise
        raise CsvIngestionError(
            f"{file_type} 包含无法解析的日期或数值",
            code="invalid_values",
        ) from error
    text_columns = set(_required(file_type)) - {
        "order_time", "quantity", "actual_amount", "sale_price", "unit_cost", "review_time", "rating"
    }
    for column in text_columns:
        frame[column] = frame[column].fillna("").astype(str).str.strip()
    if any((frame[column] == "").any() for column in text_columns if column != "content"):
        raise CsvIngestionError(f"{file_type} 的必填文本字段存在空值", code="invalid_values")
    return frame.drop_duplicates().reset_index(drop=True)


def mapping_summary(frame: pd.DataFrame, file_type: str) -> dict[str, Any]:
    mapping = suggest_mapping(frame, file_type)
    required = list(_required(file_type))
    return {
        "columns": [str(column) for column in frame.columns],
        "required_columns": required,
        "suggested_mapping": mapping,
        "missing_columns": [column for column in required if column not in mapping],
        "row_count": int(len(frame)),
    }


def _required(file_type: str) -> tuple[str, ...]:
    try:
        return REQUIRED_COLUMNS[file_type]
    except KeyError:
        raise CsvIngestionError("不支持的文件类型", code="invalid_file_type") from None


def _normalize_headers(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    normalized.columns = [str(column).strip() for column in normalized.columns]
    if len(set(normalized.columns)) != len(normalized.columns):
        raise CsvIngestionError("CSV 表头存在重复列", code="duplicate_columns")
    return normalized


def _key(value: str) -> str:
    return "".join(character.lower() for character in str(value).strip() if character not in " _-（）()")
