# Baidu POI Analyzer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tested Baidu Place API boundary that normalizes nearby restaurant POIs and a deterministic analyzer that produces traceable competition metrics.

**Architecture:** `BaiduMapClient` owns request parameters, provider errors, and conversion from loosely typed provider JSON into Pydantic DTOs. `ExternalContextAnalyzer` consumes only normalized DTOs and produces the existing `ExternalContextData` contract, which can be persisted by `ExternalContextSnapshotService`. Tests use `httpx.MockTransport` and a synthetic fixture, so no API key or network response is persisted.

**Tech Stack:** Python 3.13, httpx, Pydantic, pytest, SQLAlchemy

---

## File Structure

- Modify `backend/app/external_context/contracts.py`: add normalized POI and search-result DTOs.
- Create `backend/app/external_context/baidu_client.py`: Place API request, provider error handling, and normalization.
- Create `backend/app/external_context/analyzer.py`: deterministic competition metrics and evidence.
- Create `backend/tests/fixtures/external/baidu_context_sample.json`: synthetic provider response.
- Create `backend/tests/test_baidu_map_client.py`: request, normalization, configuration, and error tests.
- Create `backend/tests/test_external_context_analyzer.py`: metric, warning, and snapshot composition tests.
- Create `docs/data/baidu-place-integration.md`: request contract, provider limits, and credential rules.

### Task 1: Baidu Client Boundary

**Files:**
- Modify: `backend/app/external_context/contracts.py`
- Create: `backend/app/external_context/baidu_client.py`
- Create: `backend/tests/fixtures/external/baidu_context_sample.json`
- Create: `backend/tests/test_baidu_map_client.py`

- [x] **Step 1: Add a synthetic Place API fixture**

Create a status-0 response with `total=4` and four invented POIs. Include
`location`, `uid`, `address`, `status`, and `detail_info` values for
`distance`, `tag`, `brand`, `overall_rating`, `comment_num`, and `price`.
Use strings for provider rating/comment/price values to exercise conversion.

- [x] **Step 2: Write failing client tests**

```python
import json
from pathlib import Path

import httpx
import pytest

from app.external_context.baidu_client import (
    BaiduMapClient,
    BaiduMapConfigurationError,
    BaiduMapResponseError,
)

FIXTURE = Path(__file__).parent / "fixtures/external/baidu_context_sample.json"


def test_search_nearby_sends_strict_circle_params_and_normalizes_pois():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    captured_request = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        result = BaiduMapClient("test-ak", http_client=http_client).search_nearby(
            query="奶茶",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=800,
        )

    assert captured_request.url.params["radius_limit"] == "true"
    assert captured_request.url.params["scope"] == "2"
    assert captured_request.url.params["page_size"] == "20"
    assert captured_request.url.params["coord_type"] == "3"
    assert result.total == 4
    assert result.pois[0].rating == 4.6
    assert result.pois[0].comment_count == 320
    assert result.pois[0].distance_meters == 120


def test_search_nearby_raises_provider_status_error():
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"status": 4, "message": "quota"})
    )
    with httpx.Client(transport=transport) as http_client:
        with pytest.raises(BaiduMapResponseError, match="status=4"):
            BaiduMapClient("test-ak", http_client=http_client).search_nearby(
                query="奶茶",
                latitude=30.5728,
                longitude=104.0668,
                radius_meters=800,
            )


def test_from_env_requires_server_api_key(monkeypatch):
    monkeypatch.delenv("BAIDU_MAP_AK", raising=False)
    with pytest.raises(BaiduMapConfigurationError):
        BaiduMapClient.from_env()
```

- [x] **Step 3: Run tests and verify imports fail**

Run: `cd backend; python -m pytest tests/test_baidu_map_client.py -v`

Expected: collection fails because `baidu_client.py` does not exist.

- [x] **Step 4: Add normalized POI contracts**

```python
class BaiduPoi(BaseModel):
    uid: str
    name: str
    latitude: float
    longitude: float
    address: str = ""
    business_status: str = ""
    distance_meters: int | None = None
    tag: str | None = None
    brand: str | None = None
    rating: float | None = None
    comment_count: int | None = None
    average_price: float | None = None


class BaiduPoiSearchResult(BaseModel):
    query: str
    center_latitude: float
    center_longitude: float
    coordinate_system: Literal["bd09ll"] = "bd09ll"
    radius_meters: int
    total: int
    pois: list[BaiduPoi]
```

- [x] **Step 5: Implement the client**

Implement `BaiduMapClient` with:

- Base URL `https://api.map.baidu.com/place/v2/search`.
- `from_env()` reading `BAIDU_MAP_AK`.
- GET timeout of 10 seconds.
- Parameters `query`, `location`, `radius`, `radius_limit=true`,
  `output=json`, `scope=2`, `filter=industry_type:cater`,
  `coord_type=3`, `page_size=20`, `page_num=0`, and `ak`.
- `response.raise_for_status()`.
- Provider status must equal zero.
- Helpers that convert empty or invalid numeric strings to `None`.
- `detail_info` is read in memory and only normalized DTOs are returned.

- [x] **Step 6: Run client tests**

Run: `cd backend; python -m pytest tests/test_baidu_map_client.py -v`

Expected: three passing tests.

### Task 2: Deterministic Competition Analyzer

**Files:**
- Create: `backend/app/external_context/analyzer.py`
- Create: `backend/tests/test_external_context_analyzer.py`

- [x] **Step 1: Write failing analyzer tests**

Load the synthetic fixture through `BaiduMapClient` and assert:

```python
assert context.metrics["competitor_count"] == 4
assert context.metrics["sampled_competitor_count"] == 4
assert context.metrics["average_competitor_rating"] == 4.3
assert context.metrics["average_competitor_price"] == 15.0
assert context.metrics["brand_competitor_ratio"] == 0.75
assert context.metrics["median_competitor_distance_meters"] == 285.0
assert context.metrics["competition_pressure_score"] == 38.2
assert context.evidence[0].source == "baidu_map"
assert context.evidence[0].expires_at - context.evidence[0].observed_at == timedelta(days=7)
```

Add a second test with `total=150` and one sampled POI. Assert warnings mention
the first-page sample and Baidu's 150-result cap.

- [x] **Step 2: Run tests and verify analyzer import fails**

Run: `cd backend; python -m pytest tests/test_external_context_analyzer.py -v`

Expected: collection fails because `analyzer.py` does not exist.

- [x] **Step 3: Implement deterministic metrics**

Analyze non-closed sampled POIs and calculate:

- provider `total` as `competitor_count`;
- active sampled count;
- arithmetic means for available ratings and prices;
- non-empty brand count divided by active sampled count;
- median available distance;
- data completeness as the available rating, price, brand, and distance cells
  divided by `active_count * 4`;
- pressure score:
  `min(total, 40) / 40 * 60 + brand_ratio * 20 + average_rating / 5 * 20`,
  rounded to one decimal and capped at 100.

Create evidence records for each metric with the query, center coordinate system,
radius, and sample count in scope. Use seven-day expiry.

Warnings:

- provider total exceeds returned first-page sample;
- provider total equals 150 and may be capped;
- closed POIs occur in the sample;
- no active sampled POIs;
- completeness below 0.5.

- [x] **Step 4: Run analyzer tests**

Run: `cd backend; python -m pytest tests/test_external_context_analyzer.py -v`

Expected: two passing tests.

### Task 3: Snapshot Composition and Documentation

**Files:**
- Modify: `backend/tests/test_external_context_analyzer.py`
- Create: `docs/data/baidu-place-integration.md`
- Modify: `docs/superpowers/plans/2026-07-24-baidu-poi-analyzer.md`

- [x] **Step 1: Write a failing composition test**

Build normalized context from the fixture, save it through
`ExternalContextSnapshotService`, and assert:

```python
assert snapshot.metrics_json["competitor_count"] == 4
assert snapshot.evidence_json[0]["source"] == "baidu_map"
assert "results" not in snapshot.evidence_json[0]
assert "ak" not in str(snapshot.evidence_json)
```

- [x] **Step 2: Run the composition test**

Run:

```powershell
cd backend
python -m pytest tests/test_external_context_analyzer.py -v
```

Expected: composition passes using the existing snapshot service; if it exposes
a contract mismatch, fix only that boundary and rerun.

- [x] **Step 3: Document runtime configuration and limits**

Document server-side `BAIDU_MAP_AK`, BD-09 input coordinates, no raw response
persistence, first-page sample limits, `total` cap, and the distinction between
POI competition context versus measured orders or footfall.

- [x] **Step 4: Run all external-context tests**

Run:

```powershell
cd backend
python -m pytest tests/test_external_context_model.py tests/test_external_context_snapshot_service.py tests/test_reference_dataset_contract.py tests/test_reference_dataset_repository.py tests/test_production_reference_datasets.py tests/test_baidu_map_client.py tests/test_external_context_analyzer.py -v
```

Expected: all external-context tests pass.

- [x] **Step 5: Run the complete backend regression suite**

Run: `cd backend; python -m pytest -v`

Expected: all existing tests and the new Baidu/analyzer tests pass.

Actual result on 2026-07-24: all 18 external-context tests passed, followed by
34 passing tests in the complete backend regression suite.

## Deferred Work

- Weather and walking-route APIs.
- Pagination beyond the first 20 POIs.
- A real credential smoke test.
- API endpoint and React form integration.
