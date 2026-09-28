from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.knowledge.document import AcquiredDocument, ParsedDocument
from app.knowledge.manifest import KnowledgeManifestEntry


KnowledgeAdmissionRoute = Literal[
    "rag_document",
    "normative_rag",
    "rag_and_structured_fact",
    "structured_fact",
    "live_tool",
    "discovery_only",
    "private_analytics",
    "manual_review",
]


@dataclass(frozen=True)
class SourceRoutePolicy:
    route: KnowledgeAdmissionRoute
    index_in_qdrant: bool
    extract_structured_facts: bool = False
    requires_ttl: bool = False


SOURCE_ROUTE_POLICIES: dict[str, SourceRoutePolicy] = {
    "government_statistics": SourceRoutePolicy(
        "rag_and_structured_fact", True, extract_structured_facts=True
    ),
    "official_statistics": SourceRoutePolicy(
        "rag_and_structured_fact", True, extract_structured_facts=True
    ),
    "regulation": SourceRoutePolicy("normative_rag", True),
    "standard_metadata": SourceRoutePolicy("normative_rag", True),
    "listed_company_filing": SourceRoutePolicy("rag_document", True),
    "industry_association": SourceRoutePolicy("rag_document", True),
    "industry_report": SourceRoutePolicy("rag_document", True),
    "academic_research": SourceRoutePolicy("rag_document", True),
    "commercial_property": SourceRoutePolicy(
        "rag_document", True, extract_structured_facts=True
    ),
    "brand_official": SourceRoutePolicy("rag_document", True),
    "internal_methodology": SourceRoutePolicy("rag_document", True),
    "map_platform": SourceRoutePolicy(
        "live_tool", False, extract_structured_facts=True, requires_ttl=True
    ),
    "review_platform": SourceRoutePolicy(
        "live_tool", False, extract_structured_facts=True, requires_ttl=True
    ),
    "recruitment_platform": SourceRoutePolicy(
        "live_tool", False, extract_structured_facts=True, requires_ttl=True
    ),
    "news_media": SourceRoutePolicy("discovery_only", False),
    "merchant_operating_data": SourceRoutePolicy(
        "private_analytics", False, extract_structured_facts=True
    ),
}
UNKNOWN_SOURCE_POLICY = SourceRoutePolicy("manual_review", False)


class KnowledgeDocumentQuality(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text_chars: int = Field(ge=0)
    block_count: int = Field(ge=0)
    cjk_chars: int = Field(ge=0)
    cjk_ratio: float = Field(ge=0, le=1)
    replacement_chars: int = Field(ge=0)
    replacement_ratio: float = Field(ge=0, le=1)
    numeric_tokens: int = Field(ge=0)


class KnowledgeAdmissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted_for_qdrant: bool
    route: KnowledgeAdmissionRoute
    reason_codes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    extract_structured_facts: bool = False
    requires_ttl: bool = False
    quality: KnowledgeDocumentQuality | None = None


class KnowledgeAdmissionPolicy:
    """Route sources first, then reject text that cannot support grounded answers."""

    version = "source-admission-v1"

    def classify(self, entry: KnowledgeManifestEntry) -> KnowledgeAdmissionDecision:
        policy = SOURCE_ROUTE_POLICIES.get(
            entry.source.source_type, UNKNOWN_SOURCE_POLICY
        )
        reasons = () if policy.index_in_qdrant else (_route_reason(policy.route),)
        return KnowledgeAdmissionDecision(
            accepted_for_qdrant=policy.index_in_qdrant,
            route=policy.route,
            reason_codes=reasons,
            extract_structured_facts=policy.extract_structured_facts,
            requires_ttl=policy.requires_ttl,
        )

    def assess(
        self,
        entry: KnowledgeManifestEntry,
        document: AcquiredDocument,
        parsed: ParsedDocument,
    ) -> KnowledgeAdmissionDecision:
        routed = self.classify(entry)
        if not routed.accepted_for_qdrant:
            return routed

        quality = measure_document_quality(parsed)
        reasons: list[str] = []
        warnings: list[str] = []
        minimum_chars = 200
        if quality.text_chars < minimum_chars or quality.block_count == 0:
            reasons.append("insufficient_indexable_text")
        if quality.replacement_ratio > 0.02:
            reasons.append("text_encoding_corruption")
        title_has_cjk = bool(re.search(r"[\u3400-\u9fff]", entry.source.title))
        if (
            title_has_cjk
            and document.media_type == "application/pdf"
            and quality.text_chars >= minimum_chars
            and quality.cjk_ratio < 0.03
        ):
            reasons.append("chinese_pdf_text_loss")
        if quality.text_chars >= 50_000:
            warnings.append("long_document_requires_section_aware_chunking")
        if quality.numeric_tokens >= 100 and routed.extract_structured_facts:
            warnings.append("structured_fact_extraction_recommended")
        if entry.source.reliability_tier >= 3:
            warnings.append("low_reliability_source_requires_corroboration")

        return routed.model_copy(
            update={
                "accepted_for_qdrant": not reasons,
                "reason_codes": tuple(reasons),
                "warnings": tuple(warnings),
                "quality": quality,
            }
        )


def measure_document_quality(parsed: ParsedDocument) -> KnowledgeDocumentQuality:
    text = "\n".join(block.text for block in parsed.blocks)
    text_chars = len(text)
    cjk_chars = len(re.findall(r"[\u3400-\u9fff]", text))
    replacement_chars = text.count("\ufffd")
    return KnowledgeDocumentQuality(
        text_chars=text_chars,
        block_count=len(parsed.blocks),
        cjk_chars=cjk_chars,
        cjk_ratio=round(cjk_chars / max(text_chars, 1), 6),
        replacement_chars=replacement_chars,
        replacement_ratio=round(replacement_chars / max(text_chars, 1), 6),
        numeric_tokens=len(re.findall(r"(?<!\w)-?\d+(?:\.\d+)?%?", text)),
    )


def _route_reason(route: KnowledgeAdmissionRoute) -> str:
    return {
        "live_tool": "source_requires_live_tool",
        "discovery_only": "source_is_discovery_only",
        "private_analytics": "source_requires_private_analytics",
        "structured_fact": "source_requires_structured_store",
        "manual_review": "unknown_source_type_requires_review",
    }.get(route, "source_route_not_indexable")
