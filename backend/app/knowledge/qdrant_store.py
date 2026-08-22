from __future__ import annotations

from app.knowledge.document import KnowledgeChunk
from app.knowledge.embeddings import DenseEmbeddingProvider


class QdrantKnowledgeIndexStore:
    """Qdrant staging store with dense and multilingual BM25 named vectors."""

    def __init__(
        self,
        *,
        url: str,
        api_key: str,
        collection: str,
        dense_dimensions: int = 1024,
        dense_embedder: DenseEmbeddingProvider | None = None,
        client=None,
        models_module=None,
    ) -> None:
        if (client is None) != (models_module is None):
            raise ValueError("client and models_module must be supplied together")
        if client is None or models_module is None:
            try:
                from qdrant_client import QdrantClient, models
            except ImportError as error:
                raise RuntimeError(
                    "install backend/requirements-rag.txt to use Qdrant"
                ) from error
            client = QdrantClient(
                url=url,
                api_key=api_key or None,
                cloud_inference=True,
            )
            models_module = models
        self._models = models_module
        self._client = client
        self._collection = collection
        self._dense_dimensions = dense_dimensions
        self._dense_embedder = dense_embedder
        self._retired_by_activation: dict[int, tuple[int, ...]] = {}
        self._ensure_collection()

    def stage(
        self,
        document_version_id: int,
        chunks: tuple[KnowledgeChunk, ...],
    ) -> None:
        models = self._models
        points = []
        dense_vectors = (
            self._dense_embedder.embed_documents(
                [chunk.retrieval_text for chunk in chunks]
            )
            if self._dense_embedder is not None
            else [None] * len(chunks)
        )
        if len(dense_vectors) != len(chunks):
            raise ValueError("dense embedder returned an unexpected vector count")
        for chunk, dense_vector in zip(chunks, dense_vectors, strict=True):
            if chunk.document_version_id != document_version_id:
                raise ValueError(
                    "chunk document version does not match staging version"
                )
            payload = {**chunk.payload, "version_status": "staging"}
            vectors = {
                "sparse": models.Document(
                    text=chunk.retrieval_text,
                    model="qdrant/bm25",
                    options={"tokenizer": "multilingual"},
                )
            }
            if dense_vector is not None:
                if len(dense_vector) != self._dense_dimensions:
                    raise ValueError("dense vector dimensions do not match collection")
                vectors["dense"] = dense_vector
            points.append(
                models.PointStruct(
                    id=chunk.point_id,
                    vector=vectors,
                    payload=payload,
                )
            )
        if points:
            self._client.upsert(
                collection_name=self._collection,
                points=points,
                wait=True,
            )

    def count(self, document_version_id: int) -> int:
        result = self._client.count(
            collection_name=self._collection,
            count_filter=self._version_filter(document_version_id),
            exact=True,
        )
        return result.count

    def activate(
        self,
        document_version_id: int,
        *,
        retire_version_ids: tuple[int, ...],
    ) -> None:
        for version_id in retire_version_ids:
            self._client.set_payload(
                collection_name=self._collection,
                payload={"version_status": "retired"},
                points=self._version_filter(version_id),
                wait=True,
            )
        self._client.set_payload(
            collection_name=self._collection,
            payload={"version_status": "active"},
            points=self._version_filter(document_version_id),
            wait=True,
        )
        self._retired_by_activation[document_version_id] = retire_version_ids

    def discard(self, document_version_id: int) -> None:
        self._client.delete(
            collection_name=self._collection,
            points_selector=self._version_filter(document_version_id),
            wait=True,
        )
        for version_id in self._retired_by_activation.pop(document_version_id, ()):
            self._client.set_payload(
                collection_name=self._collection,
                payload={"version_status": "active"},
                points=self._version_filter(version_id),
                wait=True,
            )

    def _ensure_collection(self) -> None:
        models = self._models
        if self._client.collection_exists(self._collection):
            return
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config={
                "dense": models.VectorParams(
                    size=self._dense_dimensions,
                    distance=models.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )
        for field_name, field_schema in (
            ("document_version_id", models.PayloadSchemaType.INTEGER),
            ("source_id", models.PayloadSchemaType.INTEGER),
            ("version_status", models.PayloadSchemaType.KEYWORD),
            ("reliability_tier", models.PayloadSchemaType.INTEGER),
            ("source_type", models.PayloadSchemaType.KEYWORD),
            ("fact_status", models.PayloadSchemaType.KEYWORD),
            ("cities", models.PayloadSchemaType.KEYWORD),
            ("categories", models.PayloadSchemaType.KEYWORD),
            ("published_at_ts", models.PayloadSchemaType.INTEGER),
            ("data_period_end_ts", models.PayloadSchemaType.INTEGER),
            ("effective_to_ts", models.PayloadSchemaType.INTEGER),
        ):
            self._client.create_payload_index(
                collection_name=self._collection,
                field_name=field_name,
                field_schema=field_schema,
                wait=True,
            )

    def _version_filter(self, document_version_id: int):
        models = self._models
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="document_version_id",
                    match=models.MatchValue(value=document_version_id),
                )
            ]
        )
