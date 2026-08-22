from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from app.db.models import KnowledgeDocumentVersion, KnowledgeSource
from app.knowledge.document import KnowledgeChunk, ParsedBlock, ParsedDocument
from app.knowledge.manifest import KnowledgeManifestEntry


@dataclass(frozen=True)
class ChunkPolicy:
    target_tokens: int
    maximum_tokens: int


POLICIES = {
    "regulation": ChunkPolicy(400, 700),
    "official_statistics": ChunkPolicy(550, 800),
    "government_statistics": ChunkPolicy(550, 800),
    "industry_report": ChunkPolicy(650, 800),
    "industry_association": ChunkPolicy(650, 800),
    "listed_company_filing": ChunkPolicy(650, 800),
    "web_article": ChunkPolicy(500, 750),
    "internal_methodology": ChunkPolicy(400, 700),
}
DEFAULT_POLICY = ChunkPolicy(500, 750)


class DeterministicKnowledgeChunker:
    version = "heading-aware-v1"

    def chunk(
        self,
        document: ParsedDocument,
        *,
        entry: KnowledgeManifestEntry,
        source: KnowledgeSource,
        version: KnowledgeDocumentVersion,
    ) -> tuple[KnowledgeChunk, ...]:
        policy = POLICIES.get(entry.source.source_type, DEFAULT_POLICY)
        groups = _group_blocks(document.blocks, policy)
        chunks = []
        for index, blocks in enumerate(groups):
            raw_text = "\n\n".join(block.text for block in blocks).strip()
            content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
            heading_path = blocks[0].heading_path
            chunk_id = f"kv{version.id}-c{index:04d}"
            point_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"market-pilot:{version.id}:{index}:{content_hash}",
                )
            )
            retrieval_text = _contextualize(
                raw_text,
                heading_path=heading_path,
                entry=entry,
            )
            chunks.append(
                KnowledgeChunk(
                    point_id=point_id,
                    chunk_id=chunk_id,
                    document_version_id=version.id,
                    chunk_index=index,
                    content_hash=content_hash,
                    raw_text=raw_text,
                    retrieval_text=retrieval_text,
                    heading_path=heading_path,
                    page_start=_minimum_page(blocks),
                    page_end=_maximum_page(blocks),
                    payload=_payload(
                        entry=entry,
                        source=source,
                        version=version,
                        chunk_id=chunk_id,
                        heading_path=heading_path,
                        raw_text=raw_text,
                        retrieval_text=retrieval_text,
                        content_hash=content_hash,
                        page_start=_minimum_page(blocks),
                        page_end=_maximum_page(blocks),
                    ),
                )
            )
        return tuple(chunks)


def _group_blocks(
    blocks: tuple[ParsedBlock, ...], policy: ChunkPolicy
) -> list[list[ParsedBlock]]:
    groups: list[list[ParsedBlock]] = []
    current: list[ParsedBlock] = []
    current_tokens = 0
    for block in blocks:
        block_tokens = _token_count(block.text)
        heading_changed = bool(
            current and current[0].heading_path != block.heading_path
        )
        exceeds_target = current_tokens + block_tokens > policy.target_tokens
        exceeds_maximum = current_tokens + block_tokens > policy.maximum_tokens
        if current and (heading_changed or exceeds_maximum or exceeds_target):
            groups.append(current)
            current = []
            current_tokens = 0
        if block_tokens <= policy.maximum_tokens:
            current.append(block)
            current_tokens += block_tokens
            continue
        if current:
            groups.append(current)
            current = []
            current_tokens = 0
        groups.extend([[part] for part in _split_oversized_block(block, policy)])
    if current:
        groups.append(current)
    return groups


def _split_oversized_block(
    block: ParsedBlock, policy: ChunkPolicy
) -> list[ParsedBlock]:
    sentences = [item.strip() for item in re.split(r"(?<=[。！？.!?])", block.text)]
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if current and _token_count(current + sentence) > policy.maximum_tokens:
            parts.append(current)
            current = ""
        if _token_count(sentence) > policy.maximum_tokens:
            width = max(100, policy.maximum_tokens)
            parts.extend(
                sentence[index : index + width]
                for index in range(0, len(sentence), width)
            )
        else:
            current += sentence
    if current:
        parts.append(current)
    return [block.model_copy(update={"text": part}) for part in parts if part]


def _token_count(text: str) -> int:
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z0-9_]+", text))
    punctuation = len(re.findall(r"[^\w\s\u3400-\u9fff]", text))
    return cjk + latin + punctuation


def _contextualize(
    text: str,
    *,
    heading_path: tuple[str, ...],
    entry: KnowledgeManifestEntry,
) -> str:
    lines = [
        f"[地区: {', '.join(entry.cities) or '全国/未限定'}]",
        f"[品类: {', '.join(entry.categories) or '未限定'}]",
        f"[来源: {entry.source.publisher}]",
        f"[发布日期: {_date(entry.published_at)}]",
        f"[数据时期: {_period(entry)}]",
        f"[事实状态: {entry.fact_status}]",
        f"[章节: {' > '.join(heading_path) or '正文'}]",
    ]
    return "\n".join(lines) + "\n\n" + text


def _payload(**values) -> dict[str, object]:
    entry = values.pop("entry")
    source = values.pop("source")
    version = values.pop("version")
    return {
        "source_id": source.id,
        "source_key": source.source_key,
        "document_version_id": version.id,
        "title": source.title,
        "publisher": source.publisher,
        "source_url": source.canonical_url,
        "source_type": source.source_type,
        "reliability_tier": source.reliability_tier,
        "published_at_ts": _timestamp(entry.published_at),
        "data_period_start_ts": _timestamp(entry.data_period_start),
        "data_period_end_ts": _timestamp(entry.data_period_end),
        "effective_to_ts": _timestamp(entry.effective_to),
        "fact_status": entry.fact_status,
        "cities": list(entry.cities),
        "categories": list(entry.categories),
        "version_status": "staging",
        **values,
    }


def _date(value: datetime | None) -> str:
    return value.date().isoformat() if value else "未知"


def _period(entry: KnowledgeManifestEntry) -> str:
    if entry.data_period_start and entry.data_period_end:
        return f"{entry.data_period_start.date()} 至 {entry.data_period_end.date()}"
    return "未声明"


def _timestamp(value: datetime | None) -> int | None:
    return int(value.timestamp()) if value else None


def _minimum_page(blocks: list[ParsedBlock]) -> int | None:
    values = [block.page_start for block in blocks if block.page_start is not None]
    return min(values) if values else None


def _maximum_page(blocks: list[ParsedBlock]) -> int | None:
    values = [block.page_end for block in blocks if block.page_end is not None]
    return max(values) if values else None
