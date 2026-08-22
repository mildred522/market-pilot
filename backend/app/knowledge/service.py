from __future__ import annotations

from typing import Protocol

from app.agent_runtime.followup_evidence import (
    EvidenceMaterial,
    EvidenceRetrievalContext,
)
from app.knowledge.contracts import KnowledgeRagSettings, KnowledgeServiceHealth
from app.knowledge.query import KnowledgeQuery, KnowledgeQueryCompiler
from app.knowledge.retriever import (
    KnowledgeRetrievalResult,
    KnowledgeRetrievalTrace,
)


class KnowledgeRetrievalBackend(Protocol):
    def retrieve(self, query: KnowledgeQuery) -> KnowledgeRetrievalResult: ...


class KnowledgeFactProvider(Protocol):
    def retrieve(self, query: KnowledgeQuery) -> tuple[EvidenceMaterial, ...]: ...


class KnowledgeRetrievalService:
    """Application boundary for optional document retrieval."""

    def __init__(
        self,
        settings: KnowledgeRagSettings,
        backend: KnowledgeRetrievalBackend | None = None,
        query_compiler: KnowledgeQueryCompiler | None = None,
        fact_provider: KnowledgeFactProvider | None = None,
    ) -> None:
        self._settings = settings
        self._backend = backend
        self._query_compiler = query_compiler or KnowledgeQueryCompiler()
        self._fact_provider = fact_provider

    @property
    def available(self) -> bool:
        return self._settings.enabled and (
            self._backend is not None or self._fact_provider is not None
        )

    def health(self) -> KnowledgeServiceHealth:
        if not self._settings.enabled:
            return KnowledgeServiceHealth(
                status="disabled",
                enabled=False,
                configured=False,
            )
        if not self.available:
            return KnowledgeServiceHealth(
                status="unavailable",
                enabled=True,
                configured=self._settings.configured,
                degradations=("retrieval_backend_unavailable",),
            )
        return KnowledgeServiceHealth(
            status="ready" if self._backend is not None else "degraded",
            enabled=True,
            configured=self._settings.configured,
            degradations=(
                () if self._backend is not None else ("retrieval_backend_unavailable",)
            ),
        )

    def retrieve(
        self, context: EvidenceRetrievalContext
    ) -> KnowledgeRetrievalResult:
        if not self._settings.enabled:
            raise LookupError("knowledge RAG is disabled")
        if not self.available:
            raise LookupError("knowledge retrieval backend is unavailable")
        query = self._query_compiler.compile(context)
        reviewed_facts = (
            self._fact_provider.retrieve(query)
            if self._fact_provider is not None
            else ()
        )
        if self._backend is None:
            return _curated_result(reviewed_facts, "retrieval_backend_unavailable")
        try:
            retrieved = self._backend.retrieve(query)
        except LookupError:
            if not reviewed_facts:
                raise
            return _curated_result(reviewed_facts, "qdrant_unavailable")
        facts_by_ref = {
            fact.canonical_ref: fact for fact in (*reviewed_facts, *retrieved.facts)
        }
        return retrieved.model_copy(update={"facts": tuple(facts_by_ref.values())})


def _curated_result(
    facts: tuple[EvidenceMaterial, ...], degradation: str
) -> KnowledgeRetrievalResult:
    if not facts:
        raise LookupError("no reviewed knowledge facts are available")
    return KnowledgeRetrievalResult(
        facts=facts,
        trace=KnowledgeRetrievalTrace(
            mode="curated",
            candidate_count=len(facts),
            selected_chunks=len(facts),
            source_count=len(
                {fact.provenance.get("url") for fact in facts if fact.provenance}
            ),
            degradations=(degradation,),
            duration_ms=0,
        ),
    )
