from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.commerce.metrics import ItemLevel, TimeWindow
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

    raw_duration = dataset.snapshot.period_end - dataset.snapshot.period_start
    raw_microseconds = raw_duration // timedelta(microseconds=1)
    end_padding = 1 if raw_microseconds % 2 else 2
    coverage_window = TimeWindow(
        start=dataset.snapshot.period_start,
        end=dataset.snapshot.period_end + timedelta(microseconds=end_padding),
    )
    comparison_duration = (coverage_window.end - coverage_window.start) / 2
    if comparison_duration <= timedelta(0):
        raise ValueError("Olist snapshot period is too short for trend evaluation")
    baseline_window = TimeWindow(
        start=coverage_window.start,
        end=coverage_window.start + comparison_duration,
    )
    current_window = TimeWindow(
        start=baseline_window.end,
        end=baseline_window.end + comparison_duration,
    )
    repository = OlistSalesFactRepository(artifact_root)
    sales = repository.product_sales(
        snapshot_id,
        coverage_window,
        item_level=ItemLevel.PRODUCT,
    )
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
        "limitations": [
            "Olist 没有采购成本，销售额不能解释利润或毛利。",
            "当前评测只验证确定性事实层和规则建议，不评价 LLM 文案质量。",
            "趋势、热点和选品使用数据覆盖期前后两个等长窗口；跨多周期增长仍需要多快照数据。",
        ],
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
