from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_runtime.metric_registry import definition_for
from app.db.models import AnalysisResult


class MetricHistoryService:
    def __init__(
        self,
        db: Session,
        *,
        project_id: int,
        current_analysis_id: int,
        current_metrics: dict[str, Any],
    ) -> None:
        self._db = db
        self._project_id = project_id
        self._current_analysis_id = current_analysis_id
        self._current_metrics = current_metrics
        current = db.get(AnalysisResult, current_analysis_id)
        if current is None or current.project_id != project_id:
            raise ValueError("current analysis does not belong to the project")
        self._stage = current.stage

    def read(self, path: str) -> dict[str, Any]:
        definition = definition_for(path)
        if definition is None:
            raise ValueError(f"unknown metric definition: {path}")
        current_value = _resolve(self._current_metrics, path)
        previous_rows = self._db.scalars(
            select(AnalysisResult)
            .where(
                AnalysisResult.project_id == self._project_id,
                AnalysisResult.id < self._current_analysis_id,
                AnalysisResult.stage == self._stage,
            )
            .order_by(AnalysisResult.id.desc())
        ).all()
        for previous in previous_rows:
            try:
                previous_value = _resolve(previous.metrics_json, path)
            except ValueError:
                continue
            if not _number(current_value) or not _number(previous_value):
                raise ValueError("metric history comparison requires numeric values")
            absolute = round(float(current_value) - float(previous_value), 4)
            relative = (
                round(absolute / float(previous_value), 4)
                if float(previous_value) != 0
                else None
            )
            return {
                "metric_ref": path,
                "current_analysis_id": self._current_analysis_id,
                "previous_analysis_id": previous.id,
                "current_value": current_value,
                "previous_value": previous_value,
                "absolute_change": absolute,
                "relative_change": relative,
                "unit": definition.unit,
                "evidence_refs": [
                    path,
                    f"history.analysis.{previous.id}.{path}",
                ],
            }
        raise ValueError(f"no prior analysis contains metric: {path}")

    def resolve(self, reference: str) -> Any:
        prefix = "history.analysis."
        if not reference.startswith(prefix):
            raise ValueError(f"invalid history reference: {reference}")
        remainder = reference.removeprefix(prefix)
        analysis_id_text, separator, path = remainder.partition(".")
        if not separator or not analysis_id_text.isdigit() or not path.startswith("metrics."):
            raise ValueError(f"invalid history reference: {reference}")
        analysis = self._db.get(AnalysisResult, int(analysis_id_text))
        if analysis is None or analysis.project_id != self._project_id:
            raise ValueError(f"unknown history reference: {reference}")
        return _resolve(analysis.metrics_json, path)


def _resolve(metrics: dict[str, Any], path: str) -> Any:
    if not path.startswith("metrics."):
        raise ValueError(f"invalid metric path: {path}")
    current: Any = metrics
    for part in path.removeprefix("metrics.").split("."):
        if isinstance(current, dict) and part in current and not part.startswith("_"):
            current = current[part]
        else:
            raise ValueError(f"metric is unavailable: {path}")
    return current


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
