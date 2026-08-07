import json
from pathlib import Path

import pytest

from app.external_context.reference_repository import (
    InvalidReferenceKey,
    ReferenceDatasetNotFound,
    ReferenceDatasetRepository,
)


def write_dataset(path: Path, dataset_id: str) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "effective_year": 2025,
                "published_at": "2026-01-01T00:00:00Z",
                "sources": [
                    {
                        "source_id": "official-statistics",
                        "title": "Official statistics",
                        "publisher": "Statistics authority",
                        "url": "https://example.com/statistics",
                        "published_at": "2026-01-01T00:00:00Z",
                        "accessed_at": "2026-07-24",
                        "source_type": "government_statistics",
                    }
                ],
                "metrics": {
                    "resident_population": {
                        "value": 21.4,
                        "unit": "million",
                        "period": "2025",
                        "source_ids": ["official-statistics"],
                        "status": "reported",
                    }
                },
                "observations": ["Large consumer market"],
                "limitations": ["Annual city-level baseline"],
            }
        ),
        encoding="utf-8",
    )


def test_repository_loads_exact_city_and_category_year(tmp_path):
    write_dataset(tmp_path / "cities/chengdu/2025.json", "city-chengdu-2025")
    write_dataset(
        tmp_path / "categories/milk-tea/2025.json",
        "category-milk-tea-2025",
    )
    repository = ReferenceDatasetRepository(tmp_path)

    assert repository.load_city("chengdu", 2025).dataset_id == "city-chengdu-2025"
    assert (
        repository.load_category("milk-tea", 2025).dataset_id
        == "category-milk-tea-2025"
    )


def test_repository_reports_missing_dataset(tmp_path):
    repository = ReferenceDatasetRepository(tmp_path)

    with pytest.raises(ReferenceDatasetNotFound):
        repository.load_city("chengdu", 2025)


def test_repository_rejects_path_traversal(tmp_path):
    repository = ReferenceDatasetRepository(tmp_path)

    with pytest.raises(InvalidReferenceKey):
        repository.load_city("../secret", 2025)
