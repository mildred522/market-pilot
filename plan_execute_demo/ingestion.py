from __future__ import annotations

import csv
from io import StringIO


REQUIRED_FIELDS = {
    "orders": ("order_id", "item_name", "quantity", "actual_amount"),
    "menu": ("item_name", "unit_cost"),
}
ALIASES = {
    "order_id": ("order_id", "订单号", "订单编号"),
    "item_name": ("item_name", "菜品名称", "商品名称"),
    "quantity": ("quantity", "数量", "商品数量"),
    "actual_amount": ("actual_amount", "实收金额", "支付金额"),
    "unit_cost": ("unit_cost", "单位成本", "成本"),
}


def inspect_csv(text: str, kind: str) -> dict[str, object]:
    reader = csv.DictReader(StringIO(text))
    headers = reader.fieldnames or []
    required = REQUIRED_FIELDS[kind]
    mapping = {
        field: next((name for name in ALIASES[field] if name in headers), None)
        for field in required
    }
    return {
        "headers": headers,
        "required_fields": list(required),
        "suggested_mapping": mapping,
        "missing_fields": [field for field, source in mapping.items() if source is None],
    }


def parse_csv(
    text: str, kind: str, mapping: dict[str, str] | None = None
) -> tuple[list[dict[str, str]], dict[str, str]]:
    inspection = inspect_csv(text, kind)
    headers = set(inspection["headers"])
    resolved = mapping or inspection["suggested_mapping"]
    required = REQUIRED_FIELDS[kind]
    invalid = [
        field
        for field in required
        if not isinstance(resolved.get(field), str) or resolved[field] not in headers
    ]
    if invalid:
        raise ValueError(f"csv_mapping_missing:{','.join(invalid)}")
    raw_rows = list(csv.DictReader(StringIO(text)))
    if not raw_rows:
        raise ValueError("csv_has_no_rows")
    rows = [{field: row[resolved[field]] for field in required} for row in raw_rows]
    return rows, {field: resolved[field] for field in required}
