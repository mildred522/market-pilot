import pytest
from pydantic import ValidationError

from app.external_context.contracts import ReferenceDataset


def valid_payload() -> dict[str, object]:
    return {
        "dataset_id": "city-chengdu-2025",
        "effective_year": 2025,
        "published_at": "2025-03-28T00:00:00+08:00",
        "sources": [
            {
                "source_id": "bulletin",
                "title": "2024 Chengdu Statistical Bulletin",
                "publisher": "Chengdu Municipal Bureau of Statistics",
                "url": "https://example.com/bulletin",
                "published_at": "2025-03-28T00:00:00+08:00",
                "accessed_at": "2026-07-24",
                "source_type": "government_statistics",
            }
        ],
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
