from datetime import datetime, timedelta
from statistics import mean, median
from typing import Any

from app.external_context.contracts import (
    BaiduPoi,
    BaiduPoiSearchResult,
    EvidenceRecord,
    ExternalContextData,
)

CLOSED_STATUSES = {"暂停营业", "可能已关闭", "已关闭"}


class ExternalContextAnalyzer:
    def analyze_competition(
        self,
        search_result: BaiduPoiSearchResult,
        *,
        observed_at: datetime,
    ) -> ExternalContextData:
        active_pois = [
            poi
            for poi in search_result.pois
            if poi.business_status not in CLOSED_STATUSES
        ]
        closed_count = len(search_result.pois) - len(active_pois)

        ratings = _available(active_pois, "rating")
        prices = _available(active_pois, "average_price")
        distances = _available(active_pois, "distance_meters")
        active_count = len(active_pois)
        brand_count = sum(bool(poi.brand) for poi in active_pois)

        average_rating = _rounded_mean(ratings)
        average_price = _rounded_mean(prices)
        brand_ratio = (
            round(brand_count / active_count, 4) if active_count else 0.0
        )
        median_distance = (
            round(float(median(distances)), 2) if distances else None
        )
        completeness = self._completeness(active_pois)
        pressure_score = round(
            min(search_result.total, 40) / 40 * 60
            + brand_ratio * 20
            + ((average_rating or 0.0) / 5) * 20,
            1,
        )

        metrics: dict[str, Any] = {
            "competitor_count": search_result.total,
            "sampled_competitor_count": active_count,
            "average_competitor_rating": average_rating,
            "average_competitor_price": average_price,
            "brand_competitor_ratio": brand_ratio,
            "median_competitor_distance_meters": median_distance,
            "data_completeness_ratio": completeness,
            "competition_pressure_score": min(pressure_score, 100.0),
        }
        scope = {
            "query": search_result.query,
            "center": {
                "latitude": search_result.center_latitude,
                "longitude": search_result.center_longitude,
                "coordinate_system": search_result.coordinate_system,
            },
            "radius_meters": search_result.radius_meters,
            "provider_total": search_result.total,
            "returned_sample_count": len(search_result.pois),
            "active_sample_count": active_count,
        }
        expires_at = observed_at + timedelta(days=7)
        evidence = [
            EvidenceRecord(
                source="baidu_map",
                label=metric_name,
                observed_at=observed_at,
                expires_at=expires_at,
                scope=scope,
                value=value,
            )
            for metric_name, value in metrics.items()
        ]

        warnings: list[str] = []
        if search_result.total > len(search_result.pois):
            warnings.append(
                "百度POI指标包含供应商总数，但评分、价格和品牌比例仅基于第一页样本"
            )
        if search_result.total >= 150:
            warnings.append("百度Place API的total最多返回150，实际竞品可能更多")
        if closed_count:
            warnings.append(
                f"第一页样本中有{closed_count}个暂停或可能关闭的POI，已从样本指标排除"
            )
        if not active_count:
            warnings.append("百度POI第一页没有可用于分析的营业样本")
        if active_count and completeness < 0.5:
            warnings.append(
                f"百度POI样本字段完整度仅为{completeness:.0%}，评分和价格指标可信度有限"
            )

        return ExternalContextData(
            metrics=metrics,
            evidence=evidence,
            warnings=warnings,
        )

    @staticmethod
    def _completeness(pois: list[BaiduPoi]) -> float:
        if not pois:
            return 0.0
        available_cells = sum(
            value not in (None, "")
            for poi in pois
            for value in (
                poi.rating,
                poi.average_price,
                poi.brand,
                poi.distance_meters,
            )
        )
        return round(available_cells / (len(pois) * 4), 4)


def _available(pois: list[BaiduPoi], field_name: str) -> list[float]:
    values = [
        getattr(poi, field_name)
        for poi in pois
        if getattr(poi, field_name) is not None
    ]
    return [float(value) for value in values]


def _rounded_mean(values: list[float]) -> float | None:
    return round(float(mean(values)), 2) if values else None
