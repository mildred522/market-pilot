from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.commerce.contracts import CommerceAnalysisMode, CommerceInteraction, CommerceScope, InteractionMode
from app.commerce.metrics import ItemLevel, TimeWindow
from app.commerce.providers import OlistDuckDBFactProvider
from app.commerce.sources.olist import OlistSalesFactRepository, OlistSourceAdapter
from app.commerce.talk import CommerceTalkRequest, CommerceTalkService
from app.commerce.warehouse import CommerceDuckDBArtifactStore, default_commerce_artifact_root


DEFAULT_CASES = Path(__file__).resolve().parents[1] / "evals" / "olist_talk_cases.json"
ELIGIBLE_STATUSES = {"delivered", "shipped", "approved", "invoiced"}


def _source_sales(directory: Path, window: TimeWindow) -> dict[str, Any]:
    orders: dict[str, str] = {}
    included: set[str] = set()
    excluded: set[str] = set()
    with (directory / "olist_orders_dataset.csv").open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            purchased_at = row["order_purchase_timestamp"]
            if not purchased_at:
                continue
            timestamp = datetime.fromisoformat(purchased_at)
            if window.start <= timestamp < window.end:
                order_id = row["order_id"]
                if row["order_status"].lower() in ELIGIBLE_STATUSES:
                    included.add(order_id)
                    orders[order_id] = row["order_status"]
                else:
                    excluded.add(order_id)

    products: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"units_sold": 0, "gross_amount": Decimal(0), "orders": set()}
    )
    with (directory / "olist_order_items_dataset.csv").open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            order_id = row["order_id"]
            if order_id not in orders:
                continue
            metric = products[row["product_id"]]
            metric["units_sold"] += 1
            metric["gross_amount"] += Decimal(row["price"])
            metric["orders"].add(order_id)
    return {"included": len(included), "excluded": len(excluded), "products": products}


def _check_sales(data: dict[str, Any], source: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if data["included_order_count"] != source["included"]:
        failures.append("included order count differs from raw orders")
    if data["excluded_order_count"] != source["excluded"]:
        failures.append("excluded order count differs from raw orders")
    observed = {metric["product_id"]: metric for metric in data["metrics"]}
    if set(observed) != set(source["products"]):
        failures.append("product IDs differ from raw order items")
    for product_id in set(observed) & set(source["products"]):
        metric = observed[product_id]
        expected = source["products"][product_id]
        if (
            Decimal(metric["units_sold"]) != expected["units_sold"]
            or Decimal(metric["gross_amount"]) != expected["gross_amount"]
            or metric["order_count"] != len(expected["orders"])
        ):
            failures.append(f"product {product_id} differs from raw order items")
    return failures[:10]


def evaluate_olist_cases(
    directory: Path,
    *,
    cases_path: Path = DEFAULT_CASES,
    artifact_root: Path | None = None,
    currency: str | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    casebook = json.loads(cases_path.read_text(encoding="utf-8"))
    if casebook["version"] not in {1, 2} or not casebook["cases"]:
        raise ValueError("unsupported or empty Olist casebook")
    adapter = OlistSourceAdapter()
    snapshot_id = adapter.snapshot_id(directory, currency=currency, timezone=timezone)
    store = CommerceDuckDBArtifactStore(artifact_root or default_commerce_artifact_root())
    snapshot = store.read_snapshot_metadata(snapshot_id)
    if snapshot is None or snapshot.content_hash != adapter.snapshot_content_hash(
        directory, currency=currency, timezone=timezone
    ):
        raise ValueError("missing or mismatched Olist artifact; import the same source first")
    if snapshot.schema_version != "olist-canonical-v2" or snapshot.mode is not CommerceAnalysisMode.BENCHMARK:
        raise ValueError("casebook requires an Olist benchmark artifact")

    windows = {
        name: (TimeWindow.model_validate(value["previous"]), TimeWindow.model_validate(value["current"]))
        for name, value in casebook["windows"].items()
    }
    if any(
        bound.tzinfo is not None
        for previous, current in windows.values()
        for bound in (previous.start, previous.end, current.start, current.end)
    ):
        raise ValueError("Olist casebook windows must use source-clock timestamps without timezone offsets")
    if not all(
        snapshot.period_start.replace(tzinfo=None) <= previous.start < previous.end <= current.start
        and current.end <= snapshot.period_end.replace(tzinfo=None)
        for previous, current in windows.values()
    ):
        raise ValueError("casebook windows must be historical and inside the snapshot")
    provider = OlistDuckDBFactProvider(
        snapshot_id, OlistSalesFactRepository(artifact_root or default_commerce_artifact_root())
    )
    interaction = CommerceInteraction(
        mode=InteractionMode.TALK,
        scope=CommerceScope(mode=CommerceAnalysisMode.BENCHMARK, project_id=1, snapshot_id=snapshot_id),
    )
    source_cache: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for case in casebook["cases"]:
        previous, current = windows[case["window"]]
        request = CommerceTalkRequest(
            question=case["question"], interaction=interaction,
            previous_window=previous, current_window=current,
            item_level=ItemLevel(case.get("item_level", "product")),
        )
        response = CommerceTalkService().answer(request, snapshot, provider)
        failures: list[str] = []
        if response.status != case["expected_status"]:
            failures.append(f"expected status {case['expected_status']}, got {response.status}")
        if list(response.selected_tools) != case["expected_tools"]:
            failures.append("selected tools differ from casebook")
        if response.status == "completed":
            if not all(
                execution.status == "completed"
                and f"snapshot:{snapshot_id}" in execution.evidence
                and "project:1" in execution.evidence
                for execution in response.executions
            ):
                failures.append("completed tool has missing evidence or a failed execution")
            if not any("公开基准数据" in limitation for limitation in response.limitations):
                failures.append("missing historical benchmark limitation")
            for execution in response.executions:
                if execution.tool_name != "commerce_analyze_product_sales" or execution.data is None:
                    continue
                if case["window"] not in source_cache:
                    source_cache[case["window"]] = _source_sales(directory, current)
                failures.extend(_check_sales(execution.data, source_cache[case["window"]]))
        elif response.executions:
            failures.append("refused case executed a tool")
        results.append({
            "id": case["id"], "passed": not failures, "status": response.status,
            "selected_tools": list(response.selected_tools), "failures": failures,
            "human_review": {
                "verdict": "pending",
                "focus": case.get("review_focus", []),
                "allowed_claims": case.get("allowed_claims", []),
                "disallowed_claims": case.get("disallowed_claims", []),
            },
        })
    return {
        "snapshot_id": snapshot_id,
        "casebook_version": casebook["version"],
        "automated_pass": all(result["passed"] for result in results),
        "human_review": "pending",
        "cases": results,
        "limitations": "CSV 对账仅验证历史商品销量、销售额、订单数及已拒答边界；热点解释、建议是否误导须人工审查，不能证明经营收益。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run frozen independent Olist Talk cases")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--currency", default=None)
    parser.add_argument("--timezone", default=None)
    args = parser.parse_args()
    try:
        result = evaluate_olist_cases(
            args.directory, cases_path=args.cases, artifact_root=args.artifact_root,
            currency=args.currency, timezone=args.timezone,
        )
    except (OSError, ValueError, KeyError, InvalidOperation) as error:
        parser.exit(1, f"Olist case evaluation failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["automated_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
