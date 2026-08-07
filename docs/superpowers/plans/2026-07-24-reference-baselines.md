# Reference Baselines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add validated, source-traceable 2025-effective reference datasets for Chengdu and China's milk-tea category.

**Architecture:** Strengthen the existing Pydantic boundary so every metric declares a unit, statistical period, source IDs, and reported/estimated/forecast status. Store researched values as reviewable JSON and load them through the existing exact-key repository.

**Tech Stack:** Python 3.13, Pydantic, JSON, pytest

---

## File Structure

- Modify `backend/app/external_context/contracts.py`: typed source and metric records with source-ID validation.
- Create `backend/data/reference/cities/chengdu/2025.json`: Chengdu city baseline based on the 2024 statistical bulletin.
- Create `backend/data/reference/categories/milk-tea/2025.json`: category baseline from CCFA/Meituan and HKEX disclosure.
- Create `backend/tests/test_reference_dataset_contract.py`: contract failure tests.
- Create `backend/tests/test_production_reference_datasets.py`: production dataset loading and provenance tests.
- Create `docs/data/external-reference-catalog.md`: human-readable source, definition, and limitation catalog.

### Task 1: Typed Reference Contract

**Files:**
- Modify: `backend/app/external_context/contracts.py`
- Create: `backend/tests/test_reference_dataset_contract.py`

- [x] **Step 1: Write tests that reject missing units and unknown sources**

```python
import pytest
from pydantic import ValidationError

from app.external_context.contracts import ReferenceDataset


def valid_payload() -> dict[str, object]:
    return {
        "dataset_id": "city-chengdu-2025",
        "effective_year": 2025,
        "published_at": "2025-03-28T00:00:00+08:00",
        "sources": [{
            "source_id": "bulletin",
            "title": "2024 Chengdu Statistical Bulletin",
            "publisher": "Chengdu Municipal Bureau of Statistics",
            "url": "https://example.com/bulletin",
            "published_at": "2025-03-28T00:00:00+08:00",
            "accessed_at": "2026-07-24",
            "source_type": "government_statistics",
        }],
        "metrics": {
            "resident_population": {
                "value": 2147.4,
                "unit": "ten_thousand_people",
                "period": "2024",
                "source_ids": ["bulletin"],
                "status": "reported",
            }
        },
        "observations": [],
        "limitations": [],
    }


def test_reference_metric_requires_unit():
    payload = valid_payload()
    del payload["metrics"]["resident_population"]["unit"]
    with pytest.raises(ValidationError):
        ReferenceDataset.model_validate(payload)


def test_reference_metric_rejects_unknown_source_id():
    payload = valid_payload()
    payload["metrics"]["resident_population"]["source_ids"] = ["missing"]
    with pytest.raises(ValidationError, match="unknown source"):
        ReferenceDataset.model_validate(payload)
```

- [x] **Step 2: Run tests and verify they fail because the loose contract accepts invalid metrics**

Run: `cd backend; python -m pytest tests/test_reference_dataset_contract.py -v`

Expected: both tests fail before the typed contract is implemented.

- [x] **Step 3: Add typed source and metric models**

```python
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class ReferenceSource(BaseModel):
    source_id: str
    title: str
    publisher: str
    url: HttpUrl
    published_at: datetime
    accessed_at: date
    source_type: Literal[
        "government_statistics",
        "industry_association",
        "listed_company_filing",
        "commercial_research",
    ]
    notes: str | None = None


class ReferenceMetric(BaseModel):
    value: int | float
    unit: str
    period: str
    source_ids: list[str] = Field(min_length=1)
    status: Literal["reported", "estimated", "forecast", "derived"]
    definition: str | None = None
    qualifier: Literal["exact", "about", "more_than", "less_than"] = "exact"


class ReferenceDataset(BaseModel):
    dataset_id: str
    effective_year: int
    published_at: datetime
    sources: list[ReferenceSource] = Field(min_length=1)
    metrics: dict[str, ReferenceMetric]
    observations: list[str]
    limitations: list[str]

    @model_validator(mode="after")
    def validate_metric_sources(self) -> "ReferenceDataset":
        source_ids = {source.source_id for source in self.sources}
        unknown = {
            source_id
            for metric in self.metrics.values()
            for source_id in metric.source_ids
            if source_id not in source_ids
        }
        if unknown:
            raise ValueError(f"unknown source ids: {sorted(unknown)}")
        return self
```

- [x] **Step 4: Update the existing repository fixture to use typed metrics**

Change `backend/tests/test_reference_dataset_repository.py::write_dataset` so
`sources` contains all required provenance fields and
`resident_population` contains `value`, `unit`, `period`, `source_ids`, and
`status`.

- [x] **Step 5: Run contract and repository tests**

Run:

```powershell
cd backend
python -m pytest tests/test_reference_dataset_contract.py tests/test_reference_dataset_repository.py -v
```

Expected: five passing tests.

### Task 2: Production Chengdu and Milk-Tea Datasets

**Files:**
- Create: `backend/data/reference/cities/chengdu/2025.json`
- Create: `backend/data/reference/categories/milk-tea/2025.json`
- Create: `backend/tests/test_production_reference_datasets.py`

- [x] **Step 1: Write failing production loading tests**

```python
from app.external_context.reference_repository import ReferenceDatasetRepository


def test_chengdu_2025_baseline_loads_with_city_metrics():
    dataset = ReferenceDatasetRepository().load_city("chengdu", 2025)
    assert dataset.dataset_id == "city-chengdu-2025"
    assert dataset.metrics["resident_population"].value == 2147.4
    assert dataset.metrics["food_service_revenue_growth"].value == 6.2


def test_milk_tea_2025_baseline_distinguishes_forecasts():
    dataset = ReferenceDatasetRepository().load_category("milk-tea", 2025)
    assert dataset.dataset_id == "category-milk-tea-2025"
    assert dataset.metrics["new_tea_market_size_2023"].status == "forecast"
    assert dataset.metrics["made_to_order_tea_market_size_2023"].status == "estimated"
    assert dataset.metrics["new_tea_market_size_forecast_2025"].status == "forecast"


def test_production_sources_use_public_https_urls():
    repository = ReferenceDatasetRepository()
    datasets = [
        repository.load_city("chengdu", 2025),
        repository.load_category("milk-tea", 2025),
    ]
    for dataset in datasets:
        assert dataset.sources
        assert all(str(source.url).startswith("https://") for source in dataset.sources)
        assert all(metric.source_ids for metric in dataset.metrics.values())
```

- [x] **Step 2: Run tests and verify both datasets are missing**

Run: `cd backend; python -m pytest tests/test_production_reference_datasets.py -v`

Expected: tests fail with `ReferenceDatasetNotFound`.

- [x] **Step 3: Add the Chengdu baseline**

Use the 2024 Chengdu statistical bulletin for these exact metrics:
`resident_population=2147.4 ten_thousand_people`,
`urbanization_rate=80.8 percent`,
`gdp=23511.3 hundred_million_cny`,
`service_sector_share=69.0 percent`,
`retail_sales=10835.3 hundred_million_cny`,
`retail_sales_growth=3.3 percent_yoy`,
`food_service_revenue=1355.2 hundred_million_cny`,
`food_service_revenue_growth=6.2 percent_yoy`,
`online_food_service_revenue_growth=28.1 percent_yoy`,
`university_students=130.7 ten_thousand_people`, and
`metro_passenger_trips=22.0 hundred_million_trips`.

Each metric uses source ID `chengdu-statistical-bulletin-2024`, period `2024`,
and status `reported`.

- [x] **Step 4: Add the milk-tea baseline**

Use CCFA/Meituan values for the 2023 estimated market size
`1498 hundred_million_cny`, 2025 forecast `2015 hundred_million_cny`, and
2023-08-31 active stores `51.5 ten_thousand_stores`. Use the 2025 CCFA
white-paper release for the 2024 store lower bound `66 ten_thousand_stores`,
taste preference `63.0 percent`, and health-ingredient preference
`35.3 percent`. Use the 2025 HKEX filing for the 2023 largest-brand retail
share `20.2 percent`, cup share `49.6 percent`, and affordable-store estimate
`27 ten_thousand_stores`.

- [x] **Step 5: Run production dataset tests**

Run: `cd backend; python -m pytest tests/test_production_reference_datasets.py -v`

Expected: three passing tests.

### Task 3: Catalog and Regression Verification

**Files:**
- Create: `docs/data/external-reference-catalog.md`
- Modify: `docs/superpowers/plans/2026-07-24-reference-baselines.md`

- [x] **Step 1: Document source hierarchy and non-comparable definitions**

Document that government statistics are city-wide context, Baidu will later
provide site-level context, and CCFA versus HKEX market sizes must not be
merged because their definitions differ.

- [x] **Step 2: Run all reference tests**

Run:

```powershell
cd backend
python -m pytest tests/test_reference_dataset_contract.py tests/test_reference_dataset_repository.py tests/test_production_reference_datasets.py -v
```

Expected: eight passing tests.

- [x] **Step 3: Run the complete backend regression suite**

Run: `cd backend; python -m pytest -v`

Expected: all prior tests and five new tests pass.

Actual result on 2026-07-24: all 8 reference-data tests passed, followed by
28 passing tests in the complete backend regression suite.

## Sources Used

- Chengdu Municipal Bureau of Statistics and NBS Chengdu Survey Office,
  published 2025-03-28.
- China Chain Store & Franchise Association and Meituan,
  `2023 New Tea Beverage Research Report`.
- China Chain Store & Franchise Association,
  2025 made-to-order tea nutrition white-paper release.
- HKEX, Mixue Group prospectus industry overview, published 2025-02-21.
