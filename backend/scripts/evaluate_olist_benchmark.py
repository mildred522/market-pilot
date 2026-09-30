from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.commerce.metrics import ItemLevel, TimeWindow
from app.commerce.metrics.contracts import OlistComparisonWindows
from app.commerce.sources.olist import OlistSalesFactRepository, OlistSourceAdapter
from app.commerce.warehouse import CommerceDuckDBArtifactStore
from app.commerce.ingestion import CommerceImportError


def evaluate_olist_benchmark(
    directory: Path,
    *,
    artifact_root: Path,
    currency: str | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    adapter = OlistSourceAdapter()
    snapshot_id = adapter.snapshot_id(
        directory,
        currency=currency,
        timezone=timezone,
    )
    dataset = adapter.normalize(
        directory,
        snapshot_id=snapshot_id,
        currency=currency,
        timezone=timezone,
    )
    artifact_path = CommerceDuckDBArtifactStore(artifact_root).write(
        dataset,
        staging_tables=adapter.staging_tables(directory),
    )
    if dataset.snapshot.period_start is None or dataset.snapshot.period_end is None:
        raise ValueError("Olist snapshot has no usable order period")

    coverage_window = TimeWindow(
        start=dataset.snapshot.period_start,
        end=dataset.snapshot.period_end + timedelta(microseconds=1),
    )
    repository = OlistSalesFactRepository(artifact_root)
    comparison = repository.comparison_windows(snapshot_id)
    baseline_window = comparison.baseline_window
    current_window = comparison.current_window
    sales = repository.product_sales(
        snapshot_id,
        coverage_window,
        item_level=ItemLevel.PRODUCT,
    )
    category_sales = repository.category_sales(snapshot_id, coverage_window)
    if (
        sum((metric.units_sold for metric in sales.metrics), Decimal(0))
        != sum((metric.units_sold for metric in category_sales.categories), Decimal(0))
        or sum((metric.gross_amount for metric in sales.metrics), Decimal(0))
        != sum((metric.gross_amount for metric in category_sales.categories), Decimal(0))
        or sales.included_order_count != category_sales.included_order_count
        or sales.excluded_order_count != category_sales.excluded_order_count
    ):
        raise ValueError("Olist category sales do not reconcile with product sales")
    trends = repository.product_trends(
        snapshot_id,
        current_window,
        baseline_window,
        item_level=ItemLevel.PRODUCT,
    )
    hot_products = repository.hot_products(
        snapshot_id,
        current_window,
        baseline_window,
        item_level=ItemLevel.PRODUCT,
    )
    recommendations = repository.selection_recommendations(
        snapshot_id,
        current_window,
        baseline_window,
        item_level=ItemLevel.PRODUCT,
    )
    metadata = CommerceDuckDBArtifactStore(artifact_root).read_snapshot_metadata(snapshot_id)
    if metadata is None or metadata.content_hash != dataset.snapshot.content_hash:
        raise ValueError("Olist artifact metadata does not match the source snapshot")

    backtest = _rolling_holdout_backtest(
        repository, snapshot_id, comparison, coverage_window
    )

    return {
        "ready": not dataset.quality.blocking and metadata.snapshot_id == snapshot_id,
        "snapshot": {
            "snapshot_id": snapshot_id,
            "schema_version": dataset.snapshot.schema_version,
            "content_hash": dataset.snapshot.content_hash,
            "period_start": coverage_window.start.isoformat(),
            "period_end_exclusive": coverage_window.end.isoformat(),
            "comparison_baseline_start": baseline_window.start.isoformat(),
            "comparison_baseline_end": baseline_window.end.isoformat(),
            "comparison_current_start": current_window.start.isoformat(),
            "comparison_current_end": current_window.end.isoformat(),
            "comparison_method": comparison.selection_method,
            "comparison_warning": comparison.warning,
            "comparison_baseline_orders": comparison.baseline_order_count,
            "comparison_current_orders": comparison.current_order_count,
            "artifact_path": str(artifact_path),
        },
        "quality": {
            "row_counts": dataset.quality.row_counts,
            "warning_codes": sorted(
                issue.code
                for issue in dataset.quality.issues
                if issue.severity == "warning"
            ),
        },
        "sales": {
            "product_count": len(sales.metrics),
            "included_order_count": sales.included_order_count,
            "excluded_order_count": sales.excluded_order_count,
            "top_products": [
                metric.model_dump(mode="json") for metric in sales.metrics[:10]
            ],
        },
        "category_sales": {
            "category_count": len(category_sales.categories),
            "top_categories": [
                metric.model_dump(mode="json") for metric in category_sales.categories[:10]
            ],
            "product_totals_reconciled": True,
        },
        "trends": {
            "item_count": len(trends.trends),
            "new_item_count": sum(
                trend.current is not None and trend.previous is None
                for trend in trends.trends
            ),
            "discontinued_item_count": sum(
                trend.current is None and trend.previous is not None
                for trend in trends.trends
            ),
        },
        "hot_products": {
            "candidate_count": len(hot_products.candidates),
            "label_counts": dict(
                Counter(
                    label
                    for candidate in hot_products.candidates
                    for label in candidate.labels
                )
            ),
        },
        "selection": {
            "recommendation_count": len(recommendations.recommendations),
            "type_counts": dict(
                Counter(
                    recommendation.recommendation_type
                    for recommendation in recommendations.recommendations
                )
            ),
        },
        "backtest": backtest,
        "limitations": [
            "Olist 没有采购成本，销售额不能解释利润或毛利。",
            "当前评测只验证确定性事实层和规则建议，不评价 LLM 文案质量。",
            "趋势、热点和选品使用最近密集的等长 28 天窗口；数据不足时拆分覆盖期且仅供链路验证。",
            "滚动留出仅观察自然销售方向，不能衡量建议执行效果或证明因果关系。",
        ],
    }


def _rolling_holdout_backtest(
    repository: OlistSalesFactRepository,
    snapshot_id: str,
    comparison: OlistComparisonWindows,
    coverage_window: TimeWindow,
) -> dict[str, Any]:
    unavailable = {
        "status": "unavailable",
        "reason": "没有足够密集的连续等长窗口，无法进行时间留出回测",
        "folds": [],
    }
    if comparison.selection_method != "latest_dense_28d":
        return unavailable

    duration = comparison.current_window.end - comparison.current_window.start
    minimum_orders = max(
        20, min(comparison.current_order_count, comparison.baseline_order_count) // 4
    )
    folds: list[dict[str, Any]] = []
    action_counts: Counter[str] = Counter()
    next_window_present: Counter[str] = Counter()
    directional_eligible: Counter[str] = Counter()
    same_direction: Counter[str] = Counter()

    for offset in range(4):
        holdout_end = comparison.current_window.end - offset * duration
        holdout = TimeWindow(start=holdout_end - duration, end=holdout_end)
        observed = TimeWindow(start=holdout.start - duration, end=holdout.start)
        baseline = TimeWindow(start=observed.start - duration, end=observed.start)
        if baseline.start < coverage_window.start:
            break
        baseline_sales = repository.product_sales(snapshot_id, baseline)
        observed_sales = repository.product_sales(snapshot_id, observed)
        holdout_sales = repository.product_sales(snapshot_id, holdout)
        counts = (
            baseline_sales.included_order_count,
            observed_sales.included_order_count,
            holdout_sales.included_order_count,
        )
        if min(counts) < minimum_orders:
            continue

        recommendations = repository.selection_recommendations(
            snapshot_id, observed, baseline
        ).recommendations
        holdout_by_item = {metric.item_id: metric for metric in holdout_sales.metrics}
        fold_actions: Counter[str] = Counter()
        fold_eligible: Counter[str] = Counter()
        fold_directions: Counter[str] = Counter()
        for recommendation in recommendations:
            action = recommendation.recommendation_type
            action_counts[action] += 1
            fold_actions[action] += 1
            current_metric = recommendation.current
            if action in {"verify_growth", "review_decline"} and current_metric is not None:
                directional_eligible[action] += 1
                fold_eligible[action] += 1
            next_metric = holdout_by_item.get(recommendation.item_id)
            if next_metric is None:
                if action == "review_decline" and current_metric is not None:
                    same_direction[action] += 1
                    fold_directions[action] += 1
                continue
            next_window_present[action] += 1
            if current_metric is None:
                continue
            growing = (
                next_metric.units_sold > current_metric.units_sold
                and next_metric.gross_amount > current_metric.gross_amount
            )
            declining = (
                next_metric.units_sold < current_metric.units_sold
                and next_metric.gross_amount < current_metric.gross_amount
            )
            if (action == "verify_growth" and growing) or (
                action == "review_decline" and declining
            ):
                same_direction[action] += 1
                fold_directions[action] += 1
        folds.append(
            {
                "baseline_start": baseline.start.isoformat(),
                "observed_start": observed.start.isoformat(),
                "holdout_start": holdout.start.isoformat(),
                "holdout_end": holdout.end.isoformat(),
                "order_counts": list(counts),
                "action_counts": dict(fold_actions),
                "directional_eligible_counts": dict(fold_eligible),
                "same_direction_counts": {
                    action: fold_directions[action] for action in sorted(fold_eligible)
                },
            }
        )

    if not folds:
        return unavailable
    return {
        "status": "completed",
        "method": "rolling_28d_holdout",
        "fold_count": len(folds),
        "minimum_window_orders": minimum_orders,
        "action_counts": dict(action_counts),
        "next_window_present_counts": {
            action: next_window_present[action] for action in sorted(action_counts)
        },
        "directional_eligible_counts": dict(directional_eligible),
        "same_direction_counts": {
            action: same_direction[action] for action in sorted(directional_eligible)
        },
        "folds": folds,
        "interpretation": (
            "滚动窗口会重叠；只有当前窗口有成交的增长核验和下降复核才统计下一窗口方向，"
            "未成交按零计入下降；新品验证及当前已无成交的复核只统计后续有无成交。"
            "不能解释因果或衡量采取建议后的收益。"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate an Olist benchmark through the full commerce fact chain"
    )
    parser.add_argument("directory", type=Path, help="directory with Olist CSV files")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help="directory for the DuckDB artifact",
    )
    parser.add_argument("--currency", default=None, help="currency assumption, e.g. BRL")
    parser.add_argument("--timezone", default=None, help="source timezone, if known")
    args = parser.parse_args()
    artifact_root = args.artifact_root or Path(
        os.getenv(
            "COMMERCE_ARTIFACT_ROOT",
            str(Path(__file__).resolve().parents[1] / "storage" / "commerce"),
        )
    )
    try:
        result = evaluate_olist_benchmark(
            args.directory,
            artifact_root=artifact_root,
            currency=args.currency,
            timezone=args.timezone,
        )
    except CommerceImportError as error:
        for issue in error.report.issues:
            print(f"{issue.table}:{issue.row_number or '-'} {issue.code}: {issue.message}")
        return 1
    except (OSError, ValueError) as error:
        parser.exit(1, f"Olist benchmark evaluation failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
