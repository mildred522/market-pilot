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
REVIEW_VERDICTS = {"pass", "fail", "needs_review"}


def _source_sales(directory: Path, window: TimeWindow) -> dict[str, Any]:
    orders: dict[str, str] = {}
    included: set[str] = set()
    excluded: set[str] = set()
    with (directory / "olist_orders_dataset.csv").open(newline="", encoding="utf-8-sig") as source:
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

    translations: dict[str, str] = {}
    translation_path = directory / "product_category_name_translation.csv"
    if translation_path.is_file():
        with translation_path.open(newline="", encoding="utf-8-sig") as source:
            translations = {
                row["product_category_name"]: row["product_category_name_english"]
                for row in csv.DictReader(source)
                if row.get("product_category_name") and row.get("product_category_name_english")
            }
    category_by_product: dict[str, str | None] = {}
    with (directory / "olist_products_dataset.csv").open(
        newline="", encoding="utf-8-sig"
    ) as source:
        for row in csv.DictReader(source):
            raw_category = row.get("product_category_name", "")
            category_by_product[row["product_id"]] = translations.get(raw_category, raw_category) or None
    products: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "units_sold": 0,
            "gross_amount": Decimal(0),
            "orders": set(),
            "sellers": set(),
            "category_name": None,
        }
    )
    with (directory / "olist_order_items_dataset.csv").open(newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            order_id = row["order_id"]
            if order_id not in orders:
                continue
            metric = products[row["product_id"]]
            metric["category_name"] = category_by_product.get(row["product_id"])
            metric["units_sold"] += 1
            metric["gross_amount"] += Decimal(row["price"])
            metric["orders"].add(order_id)
            if row.get("seller_id"):
                metric["sellers"].add(row["seller_id"])
    for metric in products.values():
        metric["seller_count"] = len(metric.pop("sellers"))
    skus = {
        f"olist:{product_id}": dict(metric)
        for product_id, metric in products.items()
    }
    return {
        "included": len(included),
        "excluded": len(excluded),
        "products": products,
        "skus": skus,
    }


def _source_items(source: dict[str, Any], item_level: str) -> dict[str, dict[str, Any]]:
    if item_level not in {"product", "sku"}:
        raise ValueError(f"unsupported Olist item level: {item_level}")
    return source["skus" if item_level == "sku" else "products"]


def _check_sales(
    data: dict[str, Any], source: dict[str, Any], *, item_level: str = "product"
) -> list[str]:
    failures: list[str] = []
    if data["included_order_count"] != source["included"]:
        failures.append("included order count differs from raw orders")
    if data["excluded_order_count"] != source["excluded"]:
        failures.append("excluded order count differs from raw orders")
    expected_items = _source_items(source, item_level)
    observed = {metric["item_id"]: metric for metric in data["metrics"]}
    if set(observed) != set(expected_items):
        failures.append(f"{item_level} IDs differ from raw order items")
    for item_id in set(observed) & set(expected_items):
        metric = observed[item_id]
        expected = expected_items[item_id]
        expected_product_id = item_id.removeprefix("olist:") if item_level == "sku" else item_id
        if (
            metric["item_id"] != item_id
            or metric["item_level"] != item_level
            or metric["product_id"] != expected_product_id
            or Decimal(metric["units_sold"]) != expected["units_sold"]
            or Decimal(metric["gross_amount"]) != expected["gross_amount"]
            or metric["order_count"] != len(expected["orders"])
        ):
            failures.append(f"{item_level} {item_id} differs from raw order items")
    return failures[:10]


def _check_product_trends(
    data: dict[str, Any], previous: dict[str, Any], current: dict[str, Any], *,
    item_level: str = "product",
) -> list[str]:
    previous_products = _source_items(previous, item_level)
    current_products = _source_items(current, item_level)
    items = data["items"]
    observed = {item["item_id"]: item for item in items}
    item_ids = set(previous_products) | set(current_products)
    failures: list[str] = []
    if set(observed) != item_ids or len(items) != len(item_ids):
        failures.append(f"{item_level} trend IDs differ from raw {item_level} union")
    for item_id in item_ids & set(observed):
        item = observed[item_id]
        expected = current_products.get(item_id) or previous_products[item_id]
        expected_product_id = item_id.removeprefix("olist:") if item_level == "sku" else item_id
        expected_category = expected["category_name"]
        if (
            item["item_id"] != item_id
            or item["product_id"] != expected_product_id
            or item["item_level"] != item_level
            or item["category_name"] != expected_category
        ):
            failures.append(f"{item_level} {item_id} trend grain differs from raw order items")
        for side, products in (("previous", previous_products), ("current", current_products)):
            actual = item[side]
            side_expected = products.get(item_id)
            if (actual is None) != (side_expected is None):
                failures.append(f"{item_level} {item_id} {side} presence differs from raw orders")
            elif actual is not None and side_expected is not None and (
                actual["item_id"] != item_id
                or actual["product_id"] != expected_product_id
                or actual["item_level"] != item_level
                or actual["category_name"] != side_expected["category_name"]
                or Decimal(actual["units_sold"]) != side_expected["units_sold"]
                or Decimal(actual["gross_amount"]) != side_expected["gross_amount"]
                or actual["order_count"] != len(side_expected["orders"])
            ):
                failures.append(f"{item_level} {item_id} {side} differs from raw orders")
        baseline = previous_products.get(item_id)
        latest = current_products.get(item_id)
        for field, rate_field in (
            ("units_sold", "units_growth_rate"),
            ("gross_amount", "gross_amount_growth_rate"),
            ("orders", "order_growth_rate"),
        ):
            baseline_value = None if baseline is None else (
                len(baseline[field]) if field == "orders" else baseline[field]
            )
            latest_value = None if latest is None else (
                len(latest[field]) if field == "orders" else latest[field]
            )
            expected_rate = (
                (Decimal(latest_value) - Decimal(baseline_value)) / Decimal(baseline_value)
                if baseline_value and latest_value is not None else None
            )
            actual_rate = item[rate_field]
            if (Decimal(actual_rate) if actual_rate is not None else None) != expected_rate:
                failures.append(f"{item_level} {item_id} {rate_field} differs from raw orders")
    return failures[:10]


def _check_hot_products(
    data: dict[str, Any], previous: dict[str, Any], current: dict[str, Any], *,
    item_level: str = "product",
) -> list[str]:
    previous_items = _source_items(previous, item_level)
    current_items = _source_items(current, item_level)
    qualified = tuple(
        (item_id, metric)
        for item_id, metric in current_items.items()
        if len(metric["orders"]) >= 3
    )
    ranked_by_units = sorted(qualified, key=lambda pair: (-pair[1]["units_sold"], pair[0]))
    ranked_by_gross = sorted(qualified, key=lambda pair: (-pair[1]["gross_amount"], pair[0]))
    leader_count = max(1, (len(qualified) + 3) // 4) if qualified else 0
    unit_leaders = {item_id for item_id, _ in ranked_by_units[:leader_count]}
    gross_leaders = {item_id for item_id, _ in ranked_by_gross[:leader_count]}
    expected: list[dict[str, Any]] = []
    for item_id, metric in qualified:
        baseline = previous_items.get(item_id)
        labels: list[str] = []
        evidence: list[str] = []
        if item_id in unit_leaders:
            labels.append("volume_leader")
            evidence.append("当前窗口销量位于商品前 25%")
        if item_id in gross_leaders:
            labels.append("revenue_leader")
            evidence.append("当前窗口销售额位于商品前 25%")
        if baseline is not None and len(baseline["orders"]) >= 3:
            units_growth = (metric["units_sold"] - baseline["units_sold"]) / baseline["units_sold"]
            gross_growth = (metric["gross_amount"] - baseline["gross_amount"]) / baseline["gross_amount"]
            if units_growth >= Decimal("0.20") and gross_growth >= Decimal("0.20"):
                labels.append("momentum")
                evidence.append("两侧各至少 3 笔订单，销量和销售额均增长至少 20%")
        if metric["seller_count"] >= 2:
            labels.append("multi_seller")
            evidence.append("当前窗口有至少 2 个卖家销售")
        if labels:
            expected.append({"item_id": item_id, "labels": labels, "evidence": evidence})
    expected.sort(
        key=lambda candidate: (
            0
            if len(candidate["labels"]) >= 3
            else 1
            if len(candidate["labels"]) == 2
            else 2,
            -len(candidate["labels"]),
            -current_items[candidate["item_id"]]["gross_amount"],
            candidate["item_id"],
        )
    )
    expected = expected[:20]
    observed = data["candidates"]
    failures: list[str] = []
    if [candidate["item_id"] for candidate in observed] != [candidate["item_id"] for candidate in expected]:
        failures.append("hot candidate IDs differ from raw order facts")
    for index, (actual, expected_candidate) in enumerate(zip(observed, expected), 1):
        item_id = expected_candidate["item_id"]
        metric = current_items[item_id]
        baseline = previous_items.get(item_id)
        current_amount = Decimal(str(metric["gross_amount"]))
        expected_units_growth = (
            (Decimal(metric["units_sold"]) - Decimal(baseline["units_sold"])) / Decimal(baseline["units_sold"])
            if baseline is not None and baseline["units_sold"] else None
        )
        expected_gross_growth = (
            (current_amount - Decimal(baseline["gross_amount"])) / Decimal(baseline["gross_amount"])
            if baseline is not None and baseline["gross_amount"] else None
        )
        expected_confidence = (
            "high"
            if len(expected_candidate["labels"]) >= 3
            else "medium"
            if len(expected_candidate["labels"]) == 2
            else "low"
        )
        actual_trend = actual["trend"]
        if (
            actual["rank"] != index
            or actual["item_level"] != item_level
            or actual["product_id"] != (item_id.removeprefix("olist:") if item_level == "sku" else item_id)
            or actual["labels"] != expected_candidate["labels"]
            or actual["confidence"] != expected_confidence
            or actual["current"]["item_id"] != item_id
            or actual["current"]["category_name"] != metric["category_name"]
            or Decimal(actual["current"]["units_sold"]) != metric["units_sold"]
            or actual["current"]["order_count"] != len(metric["orders"])
            or Decimal(actual["current"]["gross_amount"]) != metric["gross_amount"]
            or actual_trend["current"]["item_id"] != item_id
            or actual_trend["current"]["product_id"] != (item_id.removeprefix("olist:") if item_level == "sku" else item_id)
            or actual_trend["current"]["category_name"] != metric["category_name"]
            or (Decimal(actual_trend["units_growth_rate"]) if actual_trend["units_growth_rate"] is not None else None) != expected_units_growth
            or (Decimal(actual_trend["gross_amount_growth_rate"]) if actual_trend["gross_amount_growth_rate"] is not None else None) != expected_gross_growth
            or actual["evidence"] != expected_candidate["evidence"]
        ):
            failures.append(f"hot candidate {item_id} differs from raw order facts")
    return failures[:10]


def _source_categories(source: dict[str, Any]) -> dict[str | None, dict[str, Any]]:
    expected: dict[str | None, dict[str, Any]] = defaultdict(
        lambda: {"products": set(), "orders": set(), "units_sold": 0, "gross_amount": Decimal(0)}
    )
    for product_id, metric in source["products"].items():
        category = metric["category_name"]
        bucket = expected[category]
        bucket["products"].add(product_id)
        bucket["orders"].update(metric["orders"])
        bucket["units_sold"] += metric["units_sold"]
        bucket["gross_amount"] += metric["gross_amount"]
    return expected


def _check_category_sales(data: dict[str, Any], source: dict[str, Any]) -> list[str]:
    expected = _source_categories(source)
    observed = {category["category_name"]: category for category in data["categories"]}
    failures: list[str] = []
    if set(observed) != set(expected):
        failures.append("category names differ from raw product categories")
    for category in set(observed) & set(expected):
        metric = observed[category]
        expected_metric = expected[category]
        if (
            metric["product_count"] != len(expected_metric["products"])
            or metric["order_count"] != len(expected_metric["orders"])
            or Decimal(metric["units_sold"]) != expected_metric["units_sold"]
            or Decimal(metric["gross_amount"]) != expected_metric["gross_amount"]
        ):
            failures.append(f"category {category} differs from raw order items")
    return failures[:10]


def _check_category_trends(
    data: dict[str, Any], previous: dict[str, Any], current: dict[str, Any]
) -> list[str]:
    previous_categories = _source_categories(previous)
    current_categories = _source_categories(current)
    observed = {category["category_name"]: category for category in data["category_trends"]}
    names = set(previous_categories) | set(current_categories)
    failures: list[str] = []
    if set(observed) != names or len(data["category_trends"]) != len(names):
        failures.append("category trend names differ from raw category union")
    for name in names & set(observed):
        comparison = observed[name]
        for side, source in (("previous", previous_categories), ("current", current_categories)):
            actual = comparison[side]
            expected = source.get(name)
            if (actual is None) != (expected is None):
                failures.append(f"category {name} {side} presence differs from raw orders")
            elif actual is not None and expected is not None:
                if (
                    actual["category_name"] != name
                    or actual["product_count"] != len(expected["products"])
                    or actual["order_count"] != len(expected["orders"])
                    or Decimal(actual["units_sold"]) != expected["units_sold"]
                    or Decimal(actual["gross_amount"]) != expected["gross_amount"]
                ):
                    failures.append(f"category {name} {side} differs from raw orders")
        baseline = previous_categories.get(name)
        latest = current_categories.get(name)
        for field, rate_field in (
            ("units_sold", "units_growth_rate"),
            ("gross_amount", "gross_amount_growth_rate"),
            ("orders", "order_growth_rate"),
        ):
            baseline_value = None if baseline is None else (
                len(baseline[field]) if field == "orders" else baseline[field]
            )
            latest_value = None if latest is None else (
                len(latest[field]) if field == "orders" else latest[field]
            )
            expected_rate = (
                (Decimal(latest_value) - Decimal(baseline_value)) / Decimal(baseline_value)
                if baseline_value and latest_value is not None else None
            )
            actual_rate = comparison[rate_field]
            if (Decimal(actual_rate) if actual_rate is not None else None) != expected_rate:
                failures.append(f"category {name} {rate_field} differs from raw orders")
    return failures[:10]


def evaluate_olist_cases(
    directory: Path,
    *,
    cases_path: Path = DEFAULT_CASES,
    artifact_root: Path | None = None,
    currency: str | None = None,
    timezone: str | None = None,
    review_path: Path | None = None,
) -> dict[str, Any]:
    casebook = json.loads(cases_path.read_text(encoding="utf-8"))
    if casebook["version"] not in {1, 2, 3} or not casebook["cases"]:
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
    source_cache: dict[tuple[str, str], dict[str, Any]] = {}
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
                if execution.data is None:
                    continue
                current_key = (case["window"], "current")
                if current_key not in source_cache:
                    source_cache[current_key] = _source_sales(directory, current)
                if execution.tool_name == "commerce_analyze_product_sales":
                    failures.extend(_check_sales(
                        execution.data,
                        source_cache[current_key],
                        item_level=case.get("item_level", "product"),
                    ))
                elif execution.tool_name == "commerce_analyze_category_sales":
                    failures.extend(_check_category_sales(execution.data, source_cache[current_key]))
                elif execution.tool_name == "commerce_compare_category_trends":
                    previous_key = (case["window"], "previous")
                    if previous_key not in source_cache:
                        source_cache[previous_key] = _source_sales(directory, previous)
                    failures.extend(_check_category_trends(
                        execution.data, source_cache[previous_key], source_cache[current_key]
                    ))
                elif execution.tool_name == "commerce_compare_product_trends":
                    previous_key = (case["window"], "previous")
                    if previous_key not in source_cache:
                        source_cache[previous_key] = _source_sales(directory, previous)
                    failures.extend(_check_product_trends(
                        execution.data,
                        source_cache[previous_key],
                        source_cache[current_key],
                        item_level=case.get("item_level", "product"),
                    ))
                elif execution.tool_name == "commerce_discover_hot_products":
                    previous_key = (case["window"], "previous")
                    if previous_key not in source_cache:
                        source_cache[previous_key] = _source_sales(directory, previous)
                    failures.extend(_check_hot_products(
                        execution.data,
                        source_cache[previous_key],
                        source_cache[current_key],
                        item_level=case.get("item_level", "product"),
                    ))
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
    report = {
        "snapshot_id": snapshot_id,
        "casebook_version": casebook["version"],
        "automated_pass": all(result["passed"] for result in results),
        "human_review": "pending",
        "cases": results,
        "limitations": "CSV 对账验证历史商品、SKU 与品类销量、销售额、订单数、双窗变化率、热点候选标签及拒答边界；建议是否误导须人工审查，不能证明经营收益。",
    }
    return apply_human_review(report, review_path=review_path)


def apply_human_review(
    report: dict[str, Any], *, review_path: Path | None = None
) -> dict[str, Any]:
    """Merge an explicitly authored review without changing automated facts."""

    if review_path is None:
        return report
    payload = json.loads(review_path.read_text(encoding="utf-8"))
    reviewer = payload.get("reviewer")
    reviewed_at = payload.get("reviewed_at")
    reviews = payload.get("cases")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("human review requires a non-empty reviewer")
    if not isinstance(reviewed_at, str) or not reviewed_at.strip():
        raise ValueError("human review requires reviewed_at")
    try:
        parsed_reviewed_at = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("human review reviewed_at must be an ISO timestamp") from error
    if parsed_reviewed_at.tzinfo is None:
        raise ValueError("human review reviewed_at must include a timezone")
    if not isinstance(reviews, list):
        raise ValueError("human review cases must be a list")

    case_results = {case["id"]: case for case in report["cases"]}
    review_by_id: dict[str, dict[str, Any]] = {}
    for review in reviews:
        if not isinstance(review, dict) or not isinstance(review.get("id"), str):
            raise ValueError("human review case requires an id")
        case_id = review["id"]
        if case_id not in case_results:
            raise ValueError(f"human review references unknown case: {case_id}")
        if case_id in review_by_id:
            raise ValueError(f"duplicate human review case: {case_id}")
        verdict = review.get("verdict")
        if verdict not in REVIEW_VERDICTS:
            raise ValueError(f"unsupported human review verdict for {case_id}")
        notes = review.get("notes", "")
        if not isinstance(notes, str) or len(notes) > 2000:
            raise ValueError(f"human review notes are invalid for {case_id}")
        review_by_id[case_id] = {"verdict": verdict, "notes": notes}

    for case_id, case in case_results.items():
        existing = case["human_review"]
        review = review_by_id.get(case_id)
        if review is None:
            continue
        case["human_review"] = {
            **existing,
            **review,
            "reviewer": reviewer.strip(),
            "reviewed_at": reviewed_at,
        }

    reviewed_cases = [case for case in report["cases"] if case["human_review"]["verdict"] != "pending"]
    verdict_counts = {
        verdict: sum(case["human_review"]["verdict"] == verdict for case in report["cases"])
        for verdict in (*REVIEW_VERDICTS, "pending")
    }
    report["human_review"] = "completed" if len(reviewed_cases) == len(report["cases"]) else "pending"
    report["human_review_summary"] = {
        "reviewer": reviewer.strip(),
        "reviewed_at": reviewed_at,
        "verdict_counts": verdict_counts,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run frozen independent Olist Talk cases")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--currency", default=None)
    parser.add_argument("--timezone", default=None)
    parser.add_argument("--review-file", type=Path)
    args = parser.parse_args()
    try:
        result = evaluate_olist_cases(
            args.directory, cases_path=args.cases, artifact_root=args.artifact_root,
            currency=args.currency, timezone=args.timezone, review_path=args.review_file,
        )
    except (OSError, ValueError, KeyError, InvalidOperation) as error:
        parser.exit(1, f"Olist case evaluation failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["automated_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
