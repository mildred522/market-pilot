# External Context Storage Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tested storage foundation for normalized external restaurant context, versioned reference datasets, and reusable SQLite snapshots.

**Architecture:** Pydantic contracts define the provider-independent data boundary. SQLAlchemy stores normalized metrics and compact evidence, while a filesystem repository loads exact city/category/year JSON files. A snapshot service owns expiry calculation and exact-key reuse so later Baidu and Agent integrations do not depend on persistence details.

**Tech Stack:** Python 3.13, Pydantic, SQLAlchemy 2, SQLite, pytest

---

## File Structure

- Create `backend/app/external_context/__init__.py`: package exports.
- Create `backend/app/external_context/contracts.py`: normalized evidence and reference dataset contracts.
- Modify `backend/app/db/models.py`: add `ExternalContextSnapshot`.
- Create `backend/app/external_context/reference_repository.py`: exact city/category/year JSON loading and validation.
- Create `backend/app/external_context/snapshot_service.py`: snapshot persistence, earliest-expiry calculation, and reusable snapshot lookup.
- Create `backend/tests/test_external_context_model.py`: SQLite round-trip coverage.
- Create `backend/tests/test_reference_dataset_repository.py`: valid, missing, and unsafe-key repository coverage.
- Create `backend/tests/test_external_context_snapshot_service.py`: persistence and expiry behavior.

### Task 1: Normalized Contracts and SQLite Snapshot

**Files:**
- Create: `backend/app/external_context/__init__.py`
- Create: `backend/app/external_context/contracts.py`
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/test_external_context_model.py`

- [x] **Step 1: Write the failing model round-trip test**

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, ExternalContextSnapshot, Project
from app.external_context.contracts import EvidenceRecord, ExternalContextData


def test_external_context_snapshot_round_trips_normalized_json():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    observed_at = datetime(2026, 7, 24, 10, tzinfo=UTC)
    context = ExternalContextData(
        metrics={"competitor_count": 18},
        evidence=[
            EvidenceRecord(
                source="baidu_map",
                label="800m milk-tea competitors",
                observed_at=observed_at,
                expires_at=observed_at + timedelta(days=7),
                scope={"radius_meters": 800},
                value=18,
            )
        ],
        warnings=[],
    )

    with Session(engine) as session:
        project = Project(name="Chengdu milk tea", stage="pre_open")
        session.add(project)
        session.flush()
        snapshot = ExternalContextSnapshot(
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=800,
            queried_at=observed_at,
            expires_at=observed_at + timedelta(days=7),
            metrics_json=context.metrics,
            evidence_json=[
                item.model_dump(mode="json") for item in context.evidence
            ],
            warnings_json=context.warnings,
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        assert "external_context_snapshots" in inspect(engine).get_table_names()
        assert snapshot.metrics_json == {"competitor_count": 18}
        assert snapshot.evidence_json[0]["source"] == "baidu_map"
        assert snapshot.warnings_json == []
```

- [x] **Step 2: Run the test and verify the missing imports fail**

Run: `cd backend; python -m pytest tests/test_external_context_model.py -v`

Expected: collection fails because `ExternalContextSnapshot` or `app.external_context` does not exist.

- [x] **Step 3: Add the normalized contracts**

```python
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EvidenceRecord(BaseModel):
    source: str
    label: str
    observed_at: datetime
    expires_at: datetime
    scope: dict[str, Any] = Field(default_factory=dict)
    value: Any


class ExternalContextData(BaseModel):
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ReferenceDataset(BaseModel):
    dataset_id: str
    effective_year: int
    published_at: datetime
    sources: list[dict[str, Any]]
    metrics: dict[str, Any]
    observations: list[str]
    limitations: list[str]
```

- [x] **Step 4: Add the SQLAlchemy model**

```python
class ExternalContextSnapshot(Base):
    __tablename__ = "external_context_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    radius_meters: Mapped[int] = mapped_column(Integer, nullable=False)
    queried_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False
    )
    warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
```

- [x] **Step 5: Run the model test**

Run: `cd backend; python -m pytest tests/test_external_context_model.py -v`

Expected: one passing test.

### Task 2: Versioned Reference Dataset Repository

**Files:**
- Create: `backend/app/external_context/reference_repository.py`
- Test: `backend/tests/test_reference_dataset_repository.py`

- [x] **Step 1: Write failing repository tests**

```python
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
                "sources": [{"name": "official statistics"}],
                "metrics": {"resident_population": {"value": 21.4, "unit": "million"}},
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
```

- [x] **Step 2: Run the tests and verify the repository import fails**

Run: `cd backend; python -m pytest tests/test_reference_dataset_repository.py -v`

Expected: collection fails because `reference_repository.py` does not exist.

- [x] **Step 3: Implement exact-key JSON loading**

```python
import json
import re
from pathlib import Path

from pydantic import ValidationError

from app.external_context.contracts import ReferenceDataset

SAFE_KEY = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ReferenceDatasetNotFound(FileNotFoundError):
    pass


class InvalidReferenceKey(ValueError):
    pass


class InvalidReferenceDataset(ValueError):
    pass


class ReferenceDatasetRepository:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[2] / "data/reference"

    def load_city(self, city: str, year: int) -> ReferenceDataset:
        return self._load("cities", city, year)

    def load_category(self, category: str, year: int) -> ReferenceDataset:
        return self._load("categories", category, year)

    def _load(self, collection: str, key: str, year: int) -> ReferenceDataset:
        if not SAFE_KEY.fullmatch(key) or year < 2000 or year > 2100:
            raise InvalidReferenceKey(f"unsafe reference key: {key}/{year}")
        path = self.root / collection / key / f"{year}.json"
        if not path.is_file():
            raise ReferenceDatasetNotFound(str(path))
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return ReferenceDataset.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise InvalidReferenceDataset(str(path)) from exc
```

- [x] **Step 4: Run repository tests**

Run: `cd backend; python -m pytest tests/test_reference_dataset_repository.py -v`

Expected: three passing tests.

### Task 3: Snapshot Save and Reuse Service

**Files:**
- Create: `backend/app/external_context/snapshot_service.py`
- Test: `backend/tests/test_external_context_snapshot_service.py`

- [x] **Step 1: Write failing save and reuse tests**

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Project
from app.external_context.contracts import EvidenceRecord, ExternalContextData
from app.external_context.snapshot_service import ExternalContextSnapshotService


def make_context(now: datetime) -> ExternalContextData:
    return ExternalContextData(
        metrics={"competitor_count": 18},
        evidence=[
            EvidenceRecord(
                source="baidu_map",
                label="competitors",
                observed_at=now,
                expires_at=now + timedelta(days=7),
                scope={"radius_meters": 800},
                value=18,
            ),
            EvidenceRecord(
                source="baidu_weather",
                label="weather",
                observed_at=now,
                expires_at=now + timedelta(hours=1),
                scope={"city": "chengdu"},
                value="rain",
            ),
        ],
    )


def make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def test_save_uses_earliest_evidence_expiry():
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    with make_session() as session:
        project = Project(name="Chengdu milk tea", stage="pre_open")
        session.add(project)
        session.flush()
        snapshot = ExternalContextSnapshotService().save(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=800,
            queried_at=now,
            context=make_context(now),
        )

        assert snapshot.expires_at.replace(tzinfo=UTC) == now + timedelta(hours=1)


def test_find_reusable_returns_fresh_exact_match_only():
    now = datetime(2026, 7, 24, 10, tzinfo=UTC)
    with make_session() as session:
        project = Project(name="Chengdu milk tea", stage="pre_open")
        session.add(project)
        session.flush()
        service = ExternalContextSnapshotService()
        service.save(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=800,
            queried_at=now,
            context=make_context(now),
        )

        assert service.find_reusable(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=800,
            now=now + timedelta(minutes=30),
        ) is not None
        assert service.find_reusable(
            session,
            project_id=project.id,
            provider="baidu_map",
            city="chengdu",
            category="milk-tea",
            latitude=30.5728,
            longitude=104.0668,
            radius_meters=800,
            now=now + timedelta(hours=2),
        ) is None
```

- [x] **Step 2: Run tests and verify the service import fails**

Run: `cd backend; python -m pytest tests/test_external_context_snapshot_service.py -v`

Expected: collection fails because `snapshot_service.py` does not exist.

- [x] **Step 3: Implement save and exact-key reuse**

```python
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExternalContextSnapshot
from app.external_context.contracts import ExternalContextData


class ExternalContextSnapshotService:
    def save(
        self,
        session: Session,
        *,
        project_id: int,
        provider: str,
        city: str,
        category: str,
        latitude: float,
        longitude: float,
        radius_meters: int,
        queried_at: datetime,
        context: ExternalContextData,
    ) -> ExternalContextSnapshot:
        if not context.evidence:
            raise ValueError("snapshot requires at least one evidence record")
        snapshot = ExternalContextSnapshot(
            project_id=project_id,
            provider=provider,
            city=city,
            category=category,
            latitude=latitude,
            longitude=longitude,
            radius_meters=radius_meters,
            queried_at=queried_at,
            expires_at=min(item.expires_at for item in context.evidence),
            metrics_json=context.metrics,
            evidence_json=[
                item.model_dump(mode="json") for item in context.evidence
            ],
            warnings_json=context.warnings,
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)
        return snapshot

    def find_reusable(
        self,
        session: Session,
        *,
        project_id: int,
        provider: str,
        city: str,
        category: str,
        latitude: float,
        longitude: float,
        radius_meters: int,
        now: datetime,
    ) -> ExternalContextSnapshot | None:
        statement = (
            select(ExternalContextSnapshot)
            .where(
                ExternalContextSnapshot.project_id == project_id,
                ExternalContextSnapshot.provider == provider,
                ExternalContextSnapshot.city == city,
                ExternalContextSnapshot.category == category,
                ExternalContextSnapshot.latitude == latitude,
                ExternalContextSnapshot.longitude == longitude,
                ExternalContextSnapshot.radius_meters == radius_meters,
                ExternalContextSnapshot.expires_at > now,
            )
            .order_by(ExternalContextSnapshot.queried_at.desc())
            .limit(1)
        )
        return session.scalar(statement)
```

- [x] **Step 4: Run snapshot service tests**

Run: `cd backend; python -m pytest tests/test_external_context_snapshot_service.py -v`

Expected: three passing tests, including rejection of an empty evidence set.

### Task 4: Foundation Regression Verification

**Files:**
- Modify: `docs/superpowers/plans/2026-07-24-external-context-storage-foundation.md`

- [x] **Step 1: Run all external-context tests together**

Run:

```powershell
cd backend
python -m pytest tests/test_external_context_model.py tests/test_reference_dataset_repository.py tests/test_external_context_snapshot_service.py -v
```

Expected: seven passing tests.

- [x] **Step 2: Run the complete backend regression suite**

Run: `cd backend; python -m pytest -v`

Expected: all existing and seven new tests pass.

- [x] **Step 3: Record completion in this plan**

Mark each completed checkbox with `[x]`. If a test command differs because of the local environment, record the actual command and result under the corresponding step.

Actual result on 2026-07-24: 7 external-context tests passed, followed by
23 passing backend tests in the complete regression suite.

## Deferred Rounds

- Round 2: Curate Chengdu and milk-tea reference JSON with primary-source citations.
- Round 3: Add the Baidu Map client boundary, synthetic provider fixture, and deterministic external-context analyzer.
- Round 4: Integrate external evidence into pre-open analysis, Agent verification, API responses, and the React UI.
