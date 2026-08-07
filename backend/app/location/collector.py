from collections.abc import Sequence
from dataclasses import dataclass

from app.external_context.baidu_client import BaiduMapClient
from app.external_context.contracts import BaiduPoi
from app.location.contracts import NormalizedPoiFeature, PoiClassification

RING_RADII = (300, 500, 800, 1500)


@dataclass(frozen=True)
class PoiKeywordGroup:
    classification: PoiClassification
    keywords: tuple[str, ...]


class PoiCollectionResult(list[NormalizedPoiFeature]):
    def __init__(
        self,
        pois: Sequence[NormalizedPoiFeature],
        *,
        truncated: bool,
        warnings: Sequence[str],
    ) -> None:
        super().__init__(pois)
        self.truncated = truncated
        self.complete = not truncated
        self.warnings = tuple(warnings)


DEFAULT_COMPETITOR_KEYWORD_GROUPS = (
    PoiKeywordGroup(
        PoiClassification.DIRECT_COMPETITOR,
        ("奶茶", "茶饮", "现制饮品", "果茶", "饮品店"),
    ),
    PoiKeywordGroup(PoiClassification.SUBSTITUTE, ("咖啡", "甜品")),
)


class PoiCollector:
    MAX_PAGES = 8

    def __init__(
        self,
        client: BaiduMapClient,
        *,
        keyword_groups: Sequence[PoiKeywordGroup] = (
            DEFAULT_COMPETITOR_KEYWORD_GROUPS
        ),
        radii: Sequence[int] = RING_RADII,
        page_size: int = 20,
        max_pages: int = MAX_PAGES,
    ) -> None:
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= 20
        ):
            raise ValueError("page_size must be between 1 and 20")
        if (
            isinstance(max_pages, bool)
            or not isinstance(max_pages, int)
            or max_pages < 1
        ):
            raise ValueError("max_pages must be positive")
        if any(radius <= 0 for radius in radii):
            raise ValueError("radii must be positive")
        self._client = client
        self._keyword_groups = tuple(keyword_groups)
        self._radii = tuple(radii)
        self._page_size = page_size
        self._max_pages = min(max_pages, self.MAX_PAGES)

    def collect_competitors(
        self,
        *,
        latitude: float,
        longitude: float,
        max_radius_meters: int | None = None,
    ) -> PoiCollectionResult:
        radii = (
            tuple(radius for radius in self._radii if radius <= max_radius_meters)
            if max_radius_meters is not None
            else self._radii
        )
        if not radii:
            raise ValueError("max_radius_meters is below the smallest collection ring")
        collected: dict[str, NormalizedPoiFeature] = {}
        warnings: list[str] = []
        for group in self._keyword_groups:
            for keyword in group.keywords:
                for radius in radii:
                    warning = self._collect_query_pages(
                        collected,
                        keyword=keyword,
                        classification=group.classification,
                        latitude=latitude,
                        longitude=longitude,
                        radius=radius,
                    )
                    if warning is not None:
                        warnings.append(warning)
        return PoiCollectionResult(
            list(collected.values()),
            truncated=bool(warnings),
            warnings=warnings,
        )

    def _collect_query_pages(
        self,
        collected: dict[str, NormalizedPoiFeature],
        *,
        keyword: str,
        classification: PoiClassification,
        latitude: float,
        longitude: float,
        radius: int,
    ) -> str | None:
        retrieved = 0
        total = 0
        for page_num in range(self._max_pages):
            page = self._client.search_nearby_page(
                query=keyword,
                latitude=latitude,
                longitude=longitude,
                radius_meters=radius,
                page_num=page_num,
                page_size=self._page_size,
            )
            for poi in page.pois:
                incoming = self._to_feature(poi, keyword, classification)
                current = collected.get(poi.uid)
                collected[poi.uid] = (
                    incoming
                    if current is None
                    else self._merge(current, incoming)
                )
            retrieved += len(page.pois)
            total = page.total
            if (
                not page.pois
                or retrieved >= page.total
                or len(page.pois) < self._page_size
            ):
                break
        if retrieved < total:
            return (
                "POI collection truncated for "
                f"keyword={keyword!r}, radius_meters={radius}: "
                f"retrieved {retrieved} of {total}"
            )
        return None

    @staticmethod
    def _to_feature(
        poi: BaiduPoi,
        keyword: str,
        classification: PoiClassification,
    ) -> NormalizedPoiFeature:
        return NormalizedPoiFeature(
            uid=poi.uid,
            name=poi.name,
            distance_meters=poi.distance_meters,
            matched_keywords=[keyword],
            category=poi.tag,
            classifications=[classification],
            average_price=poi.average_price,
            business_status=poi.business_status or None,
            comment_count=poi.comment_count,
        )

    @staticmethod
    def _merge(
        current: NormalizedPoiFeature,
        incoming: NormalizedPoiFeature,
    ) -> NormalizedPoiFeature:
        distances = [
            distance
            for distance in (
                current.distance_meters,
                incoming.distance_meters,
            )
            if distance is not None
        ]
        return current.model_copy(
            update={
                "distance_meters": min(distances) if distances else None,
                "matched_keywords": sorted(
                    set(current.matched_keywords + incoming.matched_keywords)
                ),
                "classifications": sorted(
                    set(current.classifications + incoming.classifications),
                    key=lambda item: item.value,
                ),
                "category": current.category or incoming.category,
                "average_price": (
                    current.average_price
                    if current.average_price is not None
                    else incoming.average_price
                ),
                "business_status": (
                    current.business_status or incoming.business_status
                ),
                "comment_count": (
                    current.comment_count
                    if current.comment_count is not None
                    else incoming.comment_count
                ),
            }
        )
