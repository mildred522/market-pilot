# External Context Storage Design

> Baseline status: this document describes the delivered structured external-context
> MVP. The proposed document-knowledge extension is defined separately in
> [Document Knowledge RAG Implementation Plan](rag-implementation-plan.md). It does
> not replace the storage and provider boundaries below.

## 1. Decision

The MVP will use:

- SQLite for operational records, calculated metrics, evidence metadata, and report snapshots.
- Versioned JSON files for curated city and category reference datasets.
- In-memory, request-scoped handling for raw Baidu Map API responses.
- Existing CSV upload and pandas cleaning for store operating data.

The MVP will not introduce RAG embeddings, a vector database, or a general multi-provider data platform.

## 2. Goals

- Reproduce the external evidence used by a completed analysis.
- Keep city and category reference data reviewable in Git.
- Prevent vendor response formats from leaking into Agent prompts and report schemas.
- Record source, query time, geographic scope, and data freshness.
- Leave a small boundary around Baidu integration without building unused abstractions.

## 3. Non-Goals

- Persisting a copy of Baidu's POI database.
- Synchronizing Baidu and Amap.
- Semantic search across industry reports.
- Building a generic knowledge base or document chat product.
- Adding PostgreSQL, pgvector, Chroma, Qdrant, or Milvus.

## 4. Data Classification

| Data | Storage | Reason |
| --- | --- | --- |
| Projects, orders, menu, reviews | SQLite | Structured operational data |
| Calculated external metrics | SQLite | Needed to reproduce reports |
| Evidence metadata | SQLite JSON | Variable evidence shape |
| Raw Baidu API response | Memory only | Vendor data and storage restrictions |
| City and category baselines | Versioned JSON | Low update frequency and human review |
| User CSV files | Existing upload storage | Existing MVP workflow |
| Test provider responses | Synthetic JSON fixtures | Stable, legal, deterministic tests |

## 5. SQLite Model

Add `external_context_snapshots`:

```text
id
project_id
provider
city
category
latitude
longitude
radius_meters
queried_at
expires_at
metrics_json
evidence_json
warnings_json
```

`metrics_json` stores normalized derived values such as competitor counts, brand ratio, average rating, nearby scene counts, accessibility, weather context, and final location-fit scores.

`evidence_json` stores compact evidence objects:

```json
{
  "source": "baidu_map",
  "label": "800m milk-tea competitors",
  "observed_at": "2026-07-24T10:00:00Z",
  "expires_at": "2026-07-31T10:00:00Z",
  "scope": {"radius_meters": 800},
  "value": 18
}
```

Each live evidence object has its own `expires_at`. The snapshot-level `expires_at`
is the earliest expiry among its live evidence, so a snapshot is reusable only while
all of its live inputs remain fresh. Reference-only snapshots use the end of the
declared effective year. No raw provider payload or provider API key is stored.

## 6. Reference Dataset Layout

```text
backend/data/reference/
  cities/chengdu/2025.json
  categories/milk-tea/2025.json
backend/tests/fixtures/external/
  baidu_context_sample.json
```

Every reference file contains `dataset_id`, `effective_year`, `published_at`, `sources`, `metrics`, `observations`, and `limitations`. Numeric values include an explicit unit. Fixtures are synthetic and must not be copied from a production API response.

## 7. Read Flow

1. `BaiduMapClient` requests live external data and returns normalized application DTOs.
2. `ReferenceDatasetRepository` selects exact city/category/year JSON files.
3. `ExternalContextAnalyzer` calculates deterministic metrics.
4. `ExternalContextSnapshotService` persists metrics and evidence metadata.
5. Agent tools read normalized results, never raw provider responses.
6. The report verifier rejects conclusions without evidence metadata.

If the API is unavailable, the analysis continues with reference data and emits a degraded-data warning. If reference data is missing, the live location analysis continues and marks city/category context unavailable.

## 8. Freshness

- POI and route observations expire after 7 days.
- Weather observations expire after 1 hour.
- City/category JSON remains valid for its declared effective year.
- Snapshot reuse is controlled by the earliest live-evidence expiry.
- Expired snapshots remain readable for historical reports but are not reused for a new analysis.

## 9. RAG Decision

Exact SQL, metadata filters, API calls, and JSON lookup are the retrieval layer for this MVP. Vector search is unnecessary because city, category, year, radius, and project are explicit keys.

Document RAG becomes eligible only when the project has at least 20 maintained reports and users need open-ended retrieval across report prose. The first upgrade is SQLite FTS5 with metadata filtering. PostgreSQL plus pgvector is considered only if lexical retrieval is insufficient and the report corpus justifies another service.

As of 2026-08-18, open-ended retrieval across maintained external reports is an
explicit next-phase requirement. The proposed extension uses a separate Qdrant
document index while preserving SQLite for exact memory, facts, snapshots, and source
metadata. See the linked implementation plan and the
[Document Knowledge RAG ADR](../decisions/document-knowledge-rag.md).

## 10. Testing

- Model test verifies JSON fields and timestamps round-trip through SQLite.
- Repository tests verify exact city/category/year selection and missing-file behavior.
- Analyzer tests use synthetic fixtures and verify deterministic metrics.
- Snapshot tests verify freshness and expiry decisions.
- Service tests verify degraded behavior when either live API or reference data is unavailable.
- End-to-end tests verify reports contain source, observation time, and scope.

## 11. Acceptance Criteria

- A Chengdu milk-tea analysis can combine synthetic Baidu data and versioned references.
- A completed report can be reopened without another API call.
- No raw Baidu payload, API key, embedding, or vector database is persisted.
- Missing and expired data is visible to the Agent and the user.
- Existing pre-open and operating tests remain compatible.
