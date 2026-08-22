from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from time import perf_counter

from dotenv import load_dotenv

load_dotenv()

from app.agent_runtime.followup_evidence import EvidenceRetrievalContext
from app.knowledge.embeddings import QwenSentenceTransformerEmbeddings
from app.knowledge.query import KnowledgeQueryCompiler
from app.knowledge.rerankers import QwenCrossEncoderReranker
from app.knowledge.retriever import QdrantHybridKnowledgeRetriever
from app.services.runtime_config import runtime_config

RETRIEVAL_MODES = (
    "bm25",
    "dense",
    "hybrid",
    "hybrid_weighted",
    "hybrid_reranked",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare BM25, dense, and hybrid retrieval on labelled cases."
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("evals/cases/knowledge_retrieval_live.json"),
    )
    parser.add_argument("--top-k", type=int, default=5, choices=range(1, 13))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--segment", default=None)
    args = parser.parse_args()

    settings = runtime_config.knowledge_rag_settings()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.segment:
        cases = [case for case in cases if case.get("segment", "standard") == args.segment]
    if not cases:
        parser.error("no evaluation cases matched the requested segment")
    embedder = QwenSentenceTransformerEmbeddings(settings.dense_model)
    reranker = QwenCrossEncoderReranker(settings.reranker_model)
    compiler = KnowledgeQueryCompiler()
    warmup_started = perf_counter()
    embedder.embed_query(cases[0]["question"])
    cold_start_ms = round((perf_counter() - warmup_started) * 1000, 1)
    rows = []
    for mode in RETRIEVAL_MODES:
        retriever = QdrantHybridKnowledgeRetriever(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            collection=settings.collection,
            dense_embedder=embedder,
            reranker=reranker if mode == "hybrid_reranked" else None,
            retrieval_mode=mode,
        )
        for case in cases:
            context = EvidenceRetrievalContext(
                question=case["question"],
                purpose="评估知识检索相关性",
                success_condition="优先返回标注来源和事实",
                requirement="required",
                project_profile=case["profile"],
                as_of=datetime.now(UTC),
            )
            result = retriever.retrieve(compiler.compile(context))
            facts = result.facts[: args.top_k]
            source_ranks = [
                index
                for index, fact in enumerate(facts, start=1)
                if fact.provenance.get("source_key")
                == case["expected_source_key"]
            ]
            expected_chunk_ids = set(case.get("expected_chunk_ids", []))
            chunk_ranks = [
                index
                for index, fact in enumerate(facts, start=1)
                if fact.provenance.get("chunk_id") in expected_chunk_ids
            ]
            combined_text = "\n".join(str(fact.value) for fact in facts)
            term_hit = any(term in combined_text for term in case["expected_terms"])
            rows.append(
                {
                    "mode": mode,
                    "case_id": case["id"],
                    "segment": case.get("segment", "standard"),
                    "source_hit": bool(source_ranks),
                    "source_reciprocal_rank": (
                        1 / source_ranks[0] if source_ranks else 0
                    ),
                    "chunk_hit": bool(chunk_ranks),
                    "chunk_reciprocal_rank": (
                        1 / chunk_ranks[0] if chunk_ranks else 0
                    ),
                    "term_hit": term_hit,
                    "duration_ms": result.trace.duration_ms,
                    "top_sources": [
                        fact.provenance.get("source_key") for fact in facts[:3]
                    ],
                    "top_refs": [fact.canonical_ref for fact in facts[:3]],
                }
            )

    summary = {}
    for mode in RETRIEVAL_MODES:
        selected = [row for row in rows if row["mode"] == mode]
        summary[mode] = _summarize(selected)
    segment_summary = {
        segment: {
            mode: _summarize(
                [
                    row
                    for row in rows
                    if row["mode"] == mode and row["segment"] == segment
                ]
            )
            for mode in RETRIEVAL_MODES
        }
        for segment in sorted({row["segment"] for row in rows})
    }
    report = {
        "environment": {"embedding_cold_start_ms": cold_start_ms},
        "summary": summary,
        "segments": segment_summary,
        "cases": rows,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "environment": report["environment"],
                    "summary": summary,
                    "segments": segment_summary,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(rendered)
    return 0


def _summarize(rows: list[dict]) -> dict:
    return {
        "source_hit_rate_at_k": mean(row["source_hit"] for row in rows),
        "source_mrr_at_k": mean(row["source_reciprocal_rank"] for row in rows),
        "chunk_hit_rate_at_k": mean(row["chunk_hit"] for row in rows),
        "chunk_mrr_at_k": mean(row["chunk_reciprocal_rank"] for row in rows),
        "term_hit_rate_at_k": mean(row["term_hit"] for row in rows),
        "mean_duration_ms": round(mean(row["duration_ms"] for row in rows), 1),
        "median_duration_ms": round(median(row["duration_ms"] for row in rows), 1),
    }


if __name__ == "__main__":
    raise SystemExit(main())
