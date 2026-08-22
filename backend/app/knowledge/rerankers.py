from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Protocol


class KnowledgeReranker(Protocol):
    def score(self, query: str, documents: list[str]) -> list[float]: ...


class QwenCrossEncoderReranker:
    def __init__(
        self,
        model_name: str = "Qwen/Qwen3-Reranker-0.6B",
        *,
        device: str | None = None,
        local_files_only: bool = True,
        max_length: int = 1024,
        batch_size: int = 1,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._local_files_only = local_files_only
        self._max_length = max_length
        self._batch_size = batch_size
        self._model = None
        self._load_error: Exception | None = None
        self._lock = Lock()

    def score(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        values = self._load().predict(
            [(query, document) for document in documents],
            batch_size=self._batch_size,
            show_progress_bar=False,
        )
        return [float(value) for value in values]

    def _load(self):
        if self._model is not None:
            return self._model
        if self._load_error is not None:
            raise RuntimeError("reranker model is unavailable") from self._load_error
        with self._lock:
            if self._model is not None:
                return self._model
            if self._load_error is not None:
                raise RuntimeError(
                    "reranker model is unavailable"
                ) from self._load_error
            try:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(
                    self._model_reference(),
                    device=self._device,
                    local_files_only=self._local_files_only,
                    max_length=self._max_length,
                )
            except Exception as error:
                self._load_error = error
                raise RuntimeError("reranker model is unavailable") from error
            return self._model

    def _model_reference(self) -> str:
        path = Path(self._model_name)
        if path.exists() or not self._local_files_only:
            return self._model_name
        raise RuntimeError("reranker model is not cached")
