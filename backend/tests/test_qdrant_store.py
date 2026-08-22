from types import SimpleNamespace

from app.knowledge.document import KnowledgeChunk
from app.knowledge.qdrant_store import QdrantKnowledgeIndexStore


def test_qdrant_store_creates_named_vectors_and_rolls_back_activation():
    client = FakeQdrantClient()
    store = QdrantKnowledgeIndexStore(
        url="http://qdrant.test:6333",
        api_key="",
        collection="knowledge_test",
        client=client,
        models_module=FakeModels,
    )

    store.stage(1, (_chunk(1, "00000000-0000-0000-0000-000000000001"),))
    store.activate(1, retire_version_ids=())
    store.stage(2, (_chunk(2, "00000000-0000-0000-0000-000000000002"),))
    store.activate(2, retire_version_ids=(1,))

    assert client.collection["vectors_config"]["dense"].size == 1024
    assert client.collection["sparse_vectors_config"]["sparse"].modifier == "idf"
    assert len(client.payload_indexes) == 11
    assert client.points["00000000-0000-0000-0000-000000000001"].payload[
        "version_status"
    ] == "retired"
    new_point = client.points["00000000-0000-0000-0000-000000000002"]
    assert new_point.vector["sparse"].options == {"tokenizer": "multilingual"}
    assert store.count(2) == 1

    store.discard(2)

    assert store.count(2) == 0
    assert client.points["00000000-0000-0000-0000-000000000001"].payload[
        "version_status"
    ] == "active"


def _chunk(version_id: int, point_id: str) -> KnowledgeChunk:
    return KnowledgeChunk(
        point_id=point_id,
        chunk_id=f"kv{version_id}-c0000",
        document_version_id=version_id,
        chunk_index=0,
        content_hash="a" * 64,
        raw_text="成都餐饮客观资料",
        retrieval_text="[地区: 成都]\n\n成都餐饮客观资料",
        payload={
            "document_version_id": version_id,
            "version_status": "staging",
        },
    )


class ModelRecord:
    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)


class FakeModels:
    VectorParams = ModelRecord
    SparseVectorParams = ModelRecord
    Document = ModelRecord
    PointStruct = ModelRecord
    Filter = ModelRecord
    FieldCondition = ModelRecord
    MatchValue = ModelRecord

    class Distance:
        COSINE = "cosine"

    class Modifier:
        IDF = "idf"

    class PayloadSchemaType:
        INTEGER = "integer"
        KEYWORD = "keyword"


class FakeQdrantClient:
    def __init__(self):
        self.collection = None
        self.payload_indexes = []
        self.points = {}

    def collection_exists(self, _collection_name):
        return self.collection is not None

    def create_collection(self, **values):
        self.collection = values

    def create_payload_index(self, **values):
        self.payload_indexes.append(values)

    def upsert(self, *, points, **_values):
        for point in points:
            self.points[point.id] = point

    def count(self, *, count_filter, **_values):
        version_id = _filter_version(count_filter)
        count = sum(
            point.payload["document_version_id"] == version_id
            for point in self.points.values()
        )
        return SimpleNamespace(count=count)

    def set_payload(self, *, payload, points, **_values):
        version_id = _filter_version(points)
        for point in self.points.values():
            if point.payload["document_version_id"] == version_id:
                point.payload.update(payload)

    def delete(self, *, points_selector, **_values):
        version_id = _filter_version(points_selector)
        self.points = {
            point_id: point
            for point_id, point in self.points.items()
            if point.payload["document_version_id"] != version_id
        }


def _filter_version(value):
    return value.must[0].match.value
