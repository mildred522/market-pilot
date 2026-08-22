from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Literal


BudgetDimension = Literal[
    "model_calls",
    "replans",
    "repairs",
    "external_retrievals",
]


@dataclass(frozen=True)
class AgentRunBudget:
    max_model_calls: int = 4
    max_replans: int = 1
    max_repairs: int = 1
    max_external_retrievals: int = 2
    max_evidence_characters: int = 14_000
    run_timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        values = asdict(self)
        if any(value <= 0 for value in values.values()):
            raise ValueError("agent run budget limits must be positive")

    def limit_for(self, dimension: BudgetDimension) -> int:
        return int(getattr(self, f"max_{dimension}"))


class BudgetTracker:
    def __init__(self, budget: AgentRunBudget) -> None:
        self.budget = budget
        self._started_at = perf_counter()
        self._used: dict[BudgetDimension, int] = {
            "model_calls": 0,
            "replans": 0,
            "repairs": 0,
            "external_retrievals": 0,
        }
        self._exhausted: set[str] = set()
        self.evidence_truncated = False

    def reserve(self, dimension: BudgetDimension, amount: int = 1) -> bool:
        if amount < 1:
            raise ValueError("budget reservation amount must be positive")
        if self.time_exhausted:
            self._exhausted.add("run_timeout")
            return False
        if self._used[dimension] + amount > self.budget.limit_for(dimension):
            self._exhausted.add(dimension)
            return False
        self._used[dimension] += amount
        return True

    def consume_existing(self, dimension: BudgetDimension, amount: int) -> None:
        if amount < 0:
            raise ValueError("existing budget usage cannot be negative")
        self._used[dimension] = min(
            self.budget.limit_for(dimension),
            self._used[dimension] + amount,
        )
        if amount > self.budget.limit_for(dimension):
            self._exhausted.add(dimension)

    @property
    def time_exhausted(self) -> bool:
        return self.elapsed_ms >= round(self.budget.run_timeout_seconds * 1000)

    @property
    def elapsed_ms(self) -> int:
        return max(0, round((perf_counter() - self._started_at) * 1000))

    def mark_evidence_truncated(self, truncated: bool) -> None:
        self.evidence_truncated = self.evidence_truncated or truncated

    def snapshot(self) -> dict[str, object]:
        if self.time_exhausted:
            self._exhausted.add("run_timeout")
        return {
            "limits": {
                **asdict(self.budget),
                "run_timeout_ms": round(self.budget.run_timeout_seconds * 1000),
            },
            "used": {**self._used, "elapsed_ms": self.elapsed_ms},
            "exhausted_dimensions": sorted(self._exhausted),
            "evidence_truncated": self.evidence_truncated,
        }
