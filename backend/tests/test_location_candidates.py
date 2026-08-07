from app.external_context.contracts import BaiduPoi, BaiduPoiSearchResult
from app.location.candidates import CandidateAnchor, CandidateGenerator


def anchor(
    uid: str,
    name: str,
    latitude: float,
    longitude: float,
    *,
    anchor_type: str = "shopping_centers",
) -> CandidateAnchor:
    return CandidateAnchor(
        uid=uid,
        name=name,
        latitude=latitude,
        longitude=longitude,
        anchor_type=anchor_type,
        region="Chengdu High-tech Zone",
    )


class RegionClient:
    def __init__(self, results_by_query):
        self.results_by_query = results_by_query
        self.calls = []

    def search_region_page(self, **kwargs):
        self.calls.append(kwargs)
        pois = self.results_by_query.get(kwargs["query"], [])
        return BaiduPoiSearchResult(
            query=kwargs["query"],
            region=kwargs["region"],
            total=len(pois),
            pois=pois,
        )


def poi(index: int, *, latitude: float = 30.0) -> BaiduPoi:
    return BaiduPoi(
        uid=f"poi-{index:02d}",
        name=f"Anchor {index:02d}",
        latitude=latitude,
        longitude=104.0 + index / 1000,
    )


def test_cluster_includes_400m_boundary_and_separates_point_beyond_it():
    generator = CandidateGenerator(RegionClient({}))
    meters_per_degree = 111_195
    candidates = generator.cluster(
        [
            anchor("a", "Alpha", 0, 0),
            anchor("b", "Beta", 400 / meters_per_degree, 0),
            anchor("c", "Gamma", 801 / meters_per_degree, 0),
        ]
    )

    assert [[item.uid for item in candidate.anchors] for candidate in candidates] == [
        ["a", "b"],
        ["c"],
    ]


def test_cluster_representative_is_deterministic_medoid_with_explainable_name():
    generator = CandidateGenerator(RegionClient({}))
    anchors = [
        anchor("z", "Zulu", 30.0000, 104.0000),
        anchor("m", "Middle", 30.0010, 104.0000),
        anchor("a", "Alpha", 30.0020, 104.0000),
    ]

    forward = generator.cluster(anchors)[0]
    reverse = generator.cluster(reversed(anchors))[0]

    assert forward.representative.uid == "m"
    assert reverse.representative.uid == "m"
    assert forward.name == "Middle"
    assert (forward.latitude, forward.longitude) == (30.001, 104.0)
    assert [item.uid for item in forward.anchors] == ["a", "m", "z"]


def test_generate_uses_all_anchor_types_caps_raw_anchors_and_keeps_region_scope():
    queries = dict(CandidateGenerator.ANCHOR_QUERIES)
    client = RegionClient(
        {
            query: [poi(index + offset * 10) for index in range(10)]
            for offset, query in enumerate(queries.values())
        }
    )
    generator = CandidateGenerator(client)

    candidates = generator.generate(region="Chengdu High-tech Zone")

    assert len(client.calls) == len(CandidateGenerator.ANCHOR_QUERIES)
    assert sum(len(candidate.anchors) for candidate in candidates) <= 30
    assert {call["query"] for call in client.calls} == set(queries.values())
    assert all(call["filter"] is None for call in client.calls)
    assert all(
        item.region == "Chengdu High-tech Zone"
        for candidate in candidates
        for item in candidate.anchors
    )


def test_generate_rejects_provider_results_outside_requested_region_scope():
    client = RegionClient({})
    client.search_region_page = lambda **kwargs: BaiduPoiSearchResult(
        query=kwargs["query"],
        region="Different region",
        total=1,
        pois=[poi(1)],
    )

    assert CandidateGenerator(client).generate(region="Requested region") == []


def test_screening_prefers_anchor_diversity_then_evidence_count_stably():
    generator = CandidateGenerator(RegionClient({}))
    diverse = generator.cluster(
        [
            anchor("a", "A", 30, 104, anchor_type="shopping_centers"),
            anchor("b", "B", 30.0001, 104, anchor_type="transit_hubs"),
        ]
    )[0]
    dense = generator.cluster(
        [
            anchor(str(index), str(index), 31 + index / 100000, 105)
            for index in range(3)
        ]
    )[0]

    assert generator.screen([dense, diverse]) == [diverse, dense]
