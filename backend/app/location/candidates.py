from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

from app.external_context.contracts import BaiduPoi

EARTH_RADIUS_METERS = 6_371_008.8


@dataclass(frozen=True)
class CandidateAnchor:
    uid: str
    name: str
    latitude: float
    longitude: float
    anchor_type: str
    region: str
    address: str = ""


@dataclass(frozen=True)
class LocationCandidate:
    name: str
    latitude: float
    longitude: float
    representative: CandidateAnchor
    anchors: tuple[CandidateAnchor, ...]

    @property
    def anchor_types(self) -> tuple[str, ...]:
        return tuple(sorted({item.anchor_type for item in self.anchors}))


@dataclass(frozen=True)
class ScreeningMetrics:
    demand_proxies: int
    competitors: int
    transit: int


@dataclass(frozen=True)
class ScreenedCandidate:
    candidate: LocationCandidate
    score: float
    metrics: ScreeningMetrics


class CandidateScreener:
    RADIUS_METERS = 1500
    QUERIES = (
        "写字楼 社区 学校 商场 医院",
        "奶茶 咖啡",
        "地铁站 公交站",
    )

    def screen(self, candidates, collector) -> list[ScreenedCandidate]:
        screened = []
        for candidate in candidates:
            metrics = collector.collect(
                candidate=candidate,
                radius_meters=self.RADIUS_METERS,
                queries=self.QUERIES,
            )
            screened.append(
                ScreenedCandidate(
                    candidate=candidate,
                    score=self.score(metrics),
                    metrics=metrics,
                )
            )
        return sorted(
            screened,
            key=lambda item: (
                -item.score,
                _anchor_key(item.candidate.representative),
            ),
        )

    @staticmethod
    def score(metrics: ScreeningMetrics) -> float:
        competition_balance = max(0, 20 - abs(metrics.competitors - 5) * 4)
        return float(
            metrics.demand_proxies * 3
            + metrics.transit * 2
            + competition_balance
        )


class BaiduCandidateScreeningCollector:
    PAGE_SIZE = 10

    def __init__(self, client) -> None:
        self._client = client

    def collect(
        self,
        *,
        candidate: LocationCandidate,
        radius_meters: int,
        queries: Sequence[str],
    ) -> ScreeningMetrics:
        if len(queries) != 3:
            raise ValueError(
                "screening requires demand, competition, and transit queries"
            )
        counts = []
        for query in queries:
            page = self._client.search_nearby_page(
                query=query,
                latitude=candidate.latitude,
                longitude=candidate.longitude,
                radius_meters=radius_meters,
                page_num=0,
                page_size=self.PAGE_SIZE,
                radius_limit=True,
                scope=1,
                coord_type=3,
                filter=None,
            )
            counts.append(len(page.pois))
        return ScreeningMetrics(
            demand_proxies=counts[0],
            competitors=counts[1],
            transit=counts[2],
        )


class CandidateGenerator:
    MAX_RAW_ANCHORS = 30
    CLUSTER_RADIUS_METERS = 400
    ANCHOR_QUERIES = (
        ("shopping_centers", "购物中心 商业综合体"),
        ("transit_hubs", "地铁站 公交枢纽"),
        ("office_parks", "写字楼 产业园"),
        ("communities", "社区"),
        ("schools_universities", "学校 大学"),
        ("public_facilities", "医院 景区 公共设施"),
    )

    def __init__(self, client, *, max_raw_anchors: int = MAX_RAW_ANCHORS) -> None:
        if (
            isinstance(max_raw_anchors, bool)
            or not isinstance(max_raw_anchors, int)
            or not 1 <= max_raw_anchors <= self.MAX_RAW_ANCHORS
        ):
            raise ValueError("max_raw_anchors must be between 1 and 30")
        self._client = client
        self._max_raw_anchors = max_raw_anchors

    def generate(self, *, region: str) -> list[LocationCandidate]:
        groups: list[list[CandidateAnchor]] = []
        for anchor_type, query in self.ANCHOR_QUERIES:
            result = self._client.search_region_page(
                query=query,
                region=region,
                page_num=0,
                page_size=20,
                scope=2,
                coord_type=3,
                filter=None,
            )
            if result.region != region:
                groups.append([])
                continue
            groups.append(
                [self._to_anchor(item, anchor_type, region) for item in result.pois]
            )
        return self.cluster(self._round_robin(groups))

    def cluster(
        self, anchors: Iterable[CandidateAnchor]
    ) -> list[LocationCandidate]:
        remaining = sorted(anchors, key=_anchor_key)
        clusters: list[list[CandidateAnchor]] = []
        while remaining:
            cluster = [remaining.pop(0)]
            changed = True
            while changed:
                changed = False
                for item in tuple(remaining):
                    if any(
                        _distance(item, member)
                        <= self.CLUSTER_RADIUS_METERS + 0.01
                        for member in cluster
                    ):
                        cluster.append(item)
                        remaining.remove(item)
                        changed = True
            clusters.append(sorted(cluster, key=_anchor_key))
        return [self._candidate(items) for items in clusters]

    @staticmethod
    def screen(candidates: Sequence[LocationCandidate]) -> list[LocationCandidate]:
        return sorted(
            candidates,
            key=lambda item: (
                -len(item.anchor_types),
                -len(item.anchors),
                _anchor_key(item.representative),
            ),
        )

    def _round_robin(
        self, groups: Sequence[Sequence[CandidateAnchor]]
    ) -> list[CandidateAnchor]:
        selected: list[CandidateAnchor] = []
        seen: set[str] = set()
        for offset in range(max((len(group) for group in groups), default=0)):
            for group in groups:
                if offset >= len(group) or group[offset].uid in seen:
                    continue
                selected.append(group[offset])
                seen.add(group[offset].uid)
                if len(selected) == self._max_raw_anchors:
                    return selected
        return selected

    @staticmethod
    def _to_anchor(
        poi: BaiduPoi, anchor_type: str, region: str
    ) -> CandidateAnchor:
        return CandidateAnchor(
            uid=poi.uid,
            name=poi.name,
            latitude=poi.latitude,
            longitude=poi.longitude,
            anchor_type=anchor_type,
            region=region,
            address=poi.address,
        )

    @staticmethod
    def _candidate(
        anchors: tuple[CandidateAnchor, ...] | list[CandidateAnchor],
    ) -> LocationCandidate:
        representative = min(
            anchors,
            key=lambda item: (
                round(sum(_distance(item, other) for other in anchors), 6),
                _anchor_key(item),
            ),
        )
        return LocationCandidate(
            name=representative.name,
            latitude=representative.latitude,
            longitude=representative.longitude,
            representative=representative,
            anchors=tuple(anchors),
        )


def _anchor_key(anchor: CandidateAnchor) -> tuple[str, str, float, float]:
    return (anchor.uid, anchor.name, anchor.latitude, anchor.longitude)


def _distance(left: CandidateAnchor, right: CandidateAnchor) -> float:
    latitude_delta = radians(right.latitude - left.latitude)
    longitude_delta = radians(right.longitude - left.longitude)
    value = sin(latitude_delta / 2) ** 2 + (
        cos(radians(left.latitude))
        * cos(radians(right.latitude))
        * sin(longitude_delta / 2) ** 2
    )
    return 2 * EARTH_RADIUS_METERS * asin(sqrt(value))
