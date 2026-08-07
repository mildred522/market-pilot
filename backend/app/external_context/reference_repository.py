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
