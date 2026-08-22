# ADR: Document Knowledge RAG

- Status: Proposed
- Date: 2026-08-18

## Context

The existing external-context path can retrieve exact versioned JSON datasets and
persisted location snapshots. It cannot answer open-ended questions across reports,
regulations, filings, and methodology documents, such as finding the latest relevant
passages about Chengdu's restaurant market or comparing observed facts with older
forecasts.

Operational memory remains structured and deterministic. The new requirement is a
separate document-knowledge retrieval problem with semantic, lexical, provenance,
and freshness requirements.

## Decision

Add document RAG as one implementation behind the existing
`external_industry_context` capability:

- Docling performs structure-aware parsing and tokenizer-aware chunking.
- Qdrant stores dense Qwen3 embeddings and server-side multilingual BM25 vectors.
- Independent dense and sparse candidates are fused with RRF.
- An optional Qwen3 reranker improves final precision.
- SQL stores source identity, immutable versions, ingestion state, and reviewed
  numeric facts.
- Every selected passage is converted to `EvidenceMaterial` and then the existing
  immutable `EvidencePack` before generation.
- Curated JSON remains available as an exact-data and degradation path.

RAG is optional at runtime and ingests reviewed sources offline. It does not crawl
the open web during a user request and does not receive authority to execute actions.

## Consequences

Positive:

- Open-ended industry questions can return dated, attributable passages.
- Chinese exact terms and semantic paraphrases are both retrievable.
- The current bounded Planner, Replanner, validator, memory, and version model remain
  reusable.
- Retrieval quality can be measured independently with labelled document IDs.

Costs and risks:

- Qdrant and optional local models add storage, startup, and operational cost.
- Source licensing, freshness, versioning, and removal become maintained concerns.
- Poor chunks or metadata can create plausible but irrelevant context.
- Local Qwen3 embedding and reranking may be slow on CPU-only machines.

Controls:

- Keep heavy dependencies optional and models lazy-loaded.
- Use deterministic source and chunk IDs with staging before activation.
- Enforce metadata/freshness eligibility before ranking.
- Preserve raw text separately from contextual retrieval text.
- Benchmark BM25, dense, hybrid, and reranked paths before enabling by default.
- Fall back to curated facts or a partial answer on infrastructure failure.

## Rejected Alternatives

- Replace SQL memory with a vector database: exact metrics and revisions require
  deterministic lookup and project isolation.
- SQLite FTS5 only: useful as a baseline but insufficient for paraphrase retrieval
  and the intended hybrid-search portfolio demonstration.
- GraphRAG: current questions do not justify graph extraction and traversal cost.
- LangChain or LlamaIndex orchestration: duplicates existing application-owned Agent
  and evidence abstractions.
- ColBERT in the first release: token-level multivectors add cost before a measured
  precision gap exists.

## Implementation Reference

See [Document Knowledge RAG Implementation Plan](../design/rag-implementation-plan.md).
