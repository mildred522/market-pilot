# RAG Technology Research Brief

**Depth:** focused
**Date:** 2026-08-18
**Decision:** Select the smallest current RAG architecture that extends Market Pilot's existing evidence pipeline without replacing deterministic SQL memory or location tools.

## Executive Summary

Market Pilot should add a document-knowledge retrieval capability behind the existing `external_industry_context` capability. The recommended first production-shaped implementation is Docling structural parsing, contextualized child chunks, Qdrant dense plus server-side multilingual BM25 retrieval, RRF fusion, and Qwen3 reranking. Retrieved passages and SQL facts must be compiled into the existing `EvidencePack` before answer generation.

This is preferable to GraphRAG or a fully autonomous research loop because the initial corpus is small, the dominant problem is reliable Chinese retrieval with dates and citations, and the project already has bounded planning and claim validation.

## Current Project Constraints

- FastAPI and Python own analysis, tools, evidence assembly, and agent orchestration.
- SQLite stores exact project facts, report history, revisions, and external snapshots.
- `external_industry_context` already exists as an abstract retrieval capability.
- `EvidencePack` is the boundary used for grounded synthesis and claim validation.
- Baidu POI data is structured evidence and must not be moved into document RAG.
- The initial corpus is expected to contain tens, not millions, of maintained documents.

## Technology Landscape

| Decision | Candidates | Recommendation | Reason |
|---|---|---|---|
| Parsing | Docling, plain Markdown conversion, Unstructured | Docling | Preserves headings, tables, captions, and provenance and provides tokenizer-aware hybrid chunking. |
| Vector store | SQLite FTS5, pgvector, Qdrant Server, Qdrant Edge | Qdrant Server for the demonstrable path; keep a replaceable adapter | Native dense/sparse named vectors, metadata filtering, RRF/DBSF, multilingual BM25, and later multivector reranking. |
| Dense embedding | Qwen3 Embedding, BGE-M3, hosted embedding APIs | Qwen3-Embedding-0.6B first benchmark candidate | Chinese and multilingual support, instruction-aware retrieval, 32K context, 1024 dimensions, and a matching reranker family. |
| Lexical retrieval | SQLite FTS5, client FastEmbed BM25, Qdrant server BM25 | Qdrant server BM25 with `tokenizer=multilingual` | Default word tokenization is unsuitable for Chinese. FastEmbed currently does not expose Qdrant's multilingual tokenizer option. |
| Fusion | Raw weighted sum, DBSF, RRF | RRF initially | Dense cosine and BM25 scores are on incompatible scales; RRF is the safe default before a labeled tuning set exists. |
| Reranking | No reranker, Qwen3 cross-encoder, ColBERT late interaction | Qwen3-Reranker-0.6B | Better Chinese fit and lower implementation/storage cost than token-level multivectors. |
| Orchestration | LangChain/LlamaIndex, custom service, GraphRAG | Existing bounded planner plus a retrieval adapter | Avoids introducing a second agent framework and preserves current trace and evidence contracts. |

## Proposed Architecture

### Ingestion

1. Register the source, publisher, URL, publication date, observed data period, reliability tier, and content hash in SQL.
2. Parse PDF, DOCX, HTML, or Markdown into a structured document with Docling.
3. Split by document semantics, then enforce the embedding tokenizer budget.
4. Build a deterministic contextual prefix from metadata and heading ancestry.
5. Store raw text separately from contextualized retrieval text.
6. Generate dense vectors and server-side multilingual BM25 sparse vectors.
7. Upsert chunks idempotently to Qdrant using a deterministic source-version/chunk ID.
8. Extract important numeric facts into SQL with source chunk IDs and observed/forecast status.

### Retrieval

1. The current planner selects `external_industry_context` only when external knowledge is needed.
2. Parse city, category, entity, time requirement, document type, and user intent into typed filters.
3. Query exact SQL facts and run independent dense and sparse retrieval branches.
4. Retrieve 20-30 candidates per branch and fuse by RRF.
5. Rerank the fused top 30 and retain 5-8 chunks.
6. Expand parent sections or adjacent table chunks only when needed for interpretation.
7. Compile passages, facts, freshness warnings, and citations into `EvidencePack`.
8. Reuse the existing synthesis, revision, and claim-validation pipeline.

## Chunking Policy

| Document type | Structural unit | Initial token budget | Overlap |
|---|---|---:|---:|
| Regulation | chapter/article/paragraph | 150-500 | 0 |
| Statistical bulletin | heading section; table kept atomic | 250-650 | 40-80 for prose only |
| Industry report | heading-aware paragraph group | 350-700 | 60-100 |
| Web article | cleaned body paragraph group | 300-600 | 50-80 |
| Internal methodology | one complete rule or method | 200-500 | 0-50 |

Hard maximum is 800 tokens for the first experiment. Tables repeat their header when split. Every child stores `parent_section_id`, heading path, page range, source dates, geography, category, reliability tier, and fact status. Chunk size and overlap are benchmark variables, not permanent constants.

## Rejected First-Round Options

- GraphRAG: no demonstrated multi-hop entity-relationship requirement yet.
- ColBERT as the default reranker: stronger term-level interaction but materially higher storage and operational complexity.
- FastEmbed BM25 for Chinese: its current client implementation does not support Qdrant's multilingual tokenizer configuration.
- A large LangChain or LlamaIndex abstraction layer: duplicates the project's existing planner, tool, evidence, and trace abstractions.
- Replacing SQL memory with vectors: exact metrics, revisions, and project facts require deterministic lookup.

## Evaluation Gate

Build at least 50 labeled questions covering exact terms, semantic paraphrases, dates, forecasts, conflicting sources, policy clauses, and city/category filters. Compare BM25-only, dense-only, hybrid, and hybrid-plus-reranker.

Initial gates:

- Recall@10 >= 0.85
- NDCG@5 >= 0.75
- citation correctness >= 0.95
- unsupported numeric claims = 0
- expired or forecast evidence presented as current observation = 0
- retrieval P95, excluding answer generation, < 1.5 seconds on the demo machine

## Suggested Phases

1. Implement source registry, Docling parsing, deterministic chunks, and an in-memory retrieval adapter contract.
2. Add Qdrant dense and multilingual BM25 branches with RRF and offline retrieval tests.
3. Add Qwen3 reranking, parent expansion, freshness rules, and EvidencePack integration.
4. Benchmark Qdrant Edge and ColBERT only after the baseline evaluation set identifies a real latency or precision gap.

## Sources

- [Qwen3 Embedding and Reranker](https://qwenlm.github.io/blog/qwen3-embedding/)
- [Docling chunking](https://docling-project.github.io/docling/concepts/chunking/)
- [Anthropic Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval)
- [Qdrant full-text search and multilingual BM25](https://qdrant.tech/documentation/search/text-search/full-text-search/)
- [Qdrant hybrid queries and fusion](https://qdrant.tech/documentation/search/hybrid-queries/)
- [Qdrant hybrid retrieval and reranking](https://qdrant.tech/documentation/advanced-tutorials/reranking-hybrid-search/)
- [Qdrant Edge quickstart](https://qdrant.tech/documentation/edge/edge-quickstart/)

## Research Skill Note

This brief used the third-party `deep-research` skill in focused mode. Its useful general pattern is local project inspection followed by current official documentation, ecosystem comparison, alternative evaluation, and synthesis. Its Claude-specific paths and product-discovery sections were intentionally not copied into this project.
