from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Protocol


class DenseEmbeddingProvider(Protocol):
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class QwenSentenceTransformerEmbeddings:
    dimensions = 1024

    def __init__(
        self,
        model_name: str = "Qwen/Qwen3-Embedding-0.6B",
        *,
        device: str | None = None,
        local_files_only: bool = True,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._local_files_only = local_files_only
        self._model = None
        self._load_error: Exception | None = None
        self._lock = Lock()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        values = self._load().encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [value.tolist() for value in values]

    def embed_query(self, text: str) -> list[float]:
        values = self._load().encode(
            [text],
            prompt_name="query",
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return values[0].tolist()

    def _load(self):
        if self._model is not None:
            return self._model
        if self._load_error is not None:
            raise RuntimeError(
                "dense embedding model is unavailable"
            ) from self._load_error
        with self._lock:
            if self._model is not None:
                return self._model
            if self._load_error is not None:
                raise RuntimeError(
                    "dense embedding model is unavailable"
                ) from self._load_error
            try:
                model_reference = self._model_reference()
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(
                    model_reference,
                    device=self._device,
                    local_files_only=self._local_files_only,
                )
            except Exception as error:
                self._load_error = error
                raise RuntimeError(
                    "dense embedding model is unavailable"
                ) from error
            return self._model

    def _model_reference(self) -> str:
        path = Path(self._model_name)
        if path.exists() or not self._local_files_only:
            return self._model_name
        try:
            from huggingface_hub import snapshot_download

            return snapshot_download(
                repo_id=self._model_name,
                local_files_only=True,
            )
        except Exception as error:
            raise RuntimeError("dense embedding model is not cached") from error
