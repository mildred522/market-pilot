import httpx

from app.external_context.baidu_client import BaiduMapClient
from app.location.collector import PoiCollector, PoiKeywordGroup
from app.location.contracts import PoiClassification


def poi_payload(
    uid: str,
    *,
    name: str = "示例门店",
    distance: int = 120,
    tag: str = "美食;饮品店",
) -> dict[str, object]:
    return {
        "uid": uid,
        "name": name,
        "location": {"lat": 30.57, "lng": 104.06},
        "address": "测试路 1 号",
        "status": "1",
        "detail_info": {
            "distance": distance,
            "tag": tag,
            "price": "18",
            "comment_num": "42",
        },
    }


def test_collect_competitors_paginates_until_provider_total_is_reached():
    requested_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page_num = int(request.url.params["page_num"])
        requested_pages.append(page_num)
        results = (
            [poi_payload("tea-1"), poi_payload("tea-2")]
            if page_num == 0
            else [poi_payload("tea-3")]
        )
        return httpx.Response(
            200,
            json={"status": 0, "total": 3, "results": results},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        collector = PoiCollector(
            BaiduMapClient("test-ak", http_client=http_client),
            keyword_groups=(
                PoiKeywordGroup(
                    PoiClassification.DIRECT_COMPETITOR,
                    ("奶茶",),
                ),
            ),
            radii=(300,),
            page_size=2,
            max_pages=5,
        )
        pois = collector.collect_competitors(
            latitude=30.5728,
            longitude=104.0668,
        )

    assert requested_pages == [0, 1]
    assert {poi.uid for poi in pois} == {"tea-1", "tea-2", "tea-3"}


def test_collect_competitors_merges_duplicate_uids_and_retains_keywords():
    distances = {"奶茶": 220, "果茶": 180, "咖啡": 250}

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["query"]
        return httpx.Response(
            200,
            json={
                "status": 0,
                "total": 1,
                "results": [poi_payload("shared", distance=distances[query])],
            },
        )

    groups = (
        PoiKeywordGroup(
            PoiClassification.DIRECT_COMPETITOR,
            ("奶茶", "果茶"),
        ),
        PoiKeywordGroup(PoiClassification.SUBSTITUTE, ("咖啡",)),
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        pois = PoiCollector(
            BaiduMapClient("test-ak", http_client=http_client),
            keyword_groups=groups,
            radii=(300,),
        ).collect_competitors(latitude=30.5728, longitude=104.0668)

    assert len(pois) == 1
    assert pois[0].uid == "shared"
    assert pois[0].distance_meters == 180
    assert pois[0].matched_keywords == ["咖啡", "奶茶", "果茶"]
    assert set(pois[0].classifications) == {
        PoiClassification.DIRECT_COMPETITOR,
        PoiClassification.SUBSTITUTE,
    }
    assert pois[0].category == "美食;饮品店"
    assert pois[0].average_price == 18
    assert pois[0].comment_count == 42


def test_collect_competitors_uses_all_default_keywords_and_rings_with_call_cap():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        page_num = request.url.params["page_num"]
        query = request.url.params["query"]
        radius = request.url.params["radius"]
        return httpx.Response(
            200,
            json={
                "status": 0,
                "total": 100,
                "results": [poi_payload(f"{query}-{radius}-{page_num}")],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        pois = PoiCollector(
            BaiduMapClient("test-ak", http_client=http_client),
            page_size=1,
            max_pages=2,
        ).collect_competitors(latitude=30.5728, longitude=104.0668)

    assert len(requests) == 7 * 4 * 2
    assert len(pois) == len(requests)
    assert {request.url.params["query"] for request in requests} == {
        "奶茶",
        "茶饮",
        "现制饮品",
        "果茶",
        "饮品店",
        "咖啡",
        "甜品",
    }
    assert {int(request.url.params["radius"]) for request in requests} == {
        300,
        500,
        800,
        1500,
    }
    assert {int(request.url.params["page_num"]) for request in requests} == {
        0,
        1,
    }
