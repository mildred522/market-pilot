from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge.admission import KnowledgeAdmissionPolicy
from app.knowledge.contracts import KnowledgeSourceInput
from app.knowledge.document import (
    AcquiredDocument,
    KnowledgeChunk,
    ParsedBlock,
    ParsedDocument,
)
from app.knowledge.fact_extractor import DeterministicKnowledgeFactExtractor
from app.knowledge.manifest import KnowledgeAcquisition, KnowledgeManifestEntry


DEFAULT_MANIFEST = ROOT / "backend/data/knowledge/source-audit-manifest.json"
DEFAULT_OUTPUT = ROOT / "outputs/source-sample-audit"
MAX_DOWNLOAD_BYTES = 48 * 1024 * 1024


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit restaurant knowledge sources")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    output = args.output.resolve()
    root = ROOT.resolve()
    if root not in output.parents or output.name != "source-sample-audit":
        raise ValueError("output must be the workspace source-sample-audit directory")
    output.mkdir(parents=True, exist_ok=True)
    raw_root = output / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    with httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(90.0, connect=15.0),
        headers={"User-Agent": "MarketPilot-SourceAudit/1.0 (local research)"},
    ) as client:
        for channel in manifest["channels"]:
            for sample in channel["samples"]:
                result = audit_sample(channel, sample, raw_root, client)
                results.append(result)
                print(f"{result['status']:>12}  {channel['channel']}/{sample['id']}")

    summary = build_summary(manifest, results)
    (output / "audit-results.json").write_text(
        json.dumps({"summary": summary, "samples": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output / "report.md").write_text(
        render_report(manifest, results, summary), encoding="utf-8"
    )


def audit_sample(
    channel: dict[str, Any],
    sample: dict[str, Any],
    raw_root: Path,
    client: httpx.Client,
) -> dict[str, Any]:
    source_type = formal_source_type(channel["channel"], sample)
    route = KnowledgeAdmissionPolicy().classify(
        admission_entry(sample, source_type)
    )
    result: dict[str, Any] = {
        "channel": channel["channel"],
        "channel_label": channel["label"],
        "recommended_role": channel["recommended_role"],
        "id": sample["id"],
        "title": sample["title"],
        "publisher": sample["publisher"],
        "url": sample.get("url"),
        "capture_mode": sample["capture_mode"],
        "sample_kind": sample["sample_kind"],
        "source_type": source_type,
        "admission_route": route.route,
        "accepted_for_qdrant": route.accepted_for_qdrant,
        "admission_reason_codes": list(route.reason_codes),
        "limitations": sample.get("limitations") or sample.get("rights_note"),
        "status": "pending",
    }
    try:
        target_dir = raw_root / channel["channel"]
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            content, media_type, filename, origin = acquire(sample, client)
        except Exception:
            cached = cached_audit_sample(target_dir, sample["id"])
            if cached is None:
                raise
            content, media_type, filename = cached
            origin = "previous_audit_cache"
        target = target_dir / f"{sample['id']}{Path(filename).suffix or extension_for(media_type)}"
        target.write_bytes(content)

        text, parser_name = extract_text(content, media_type, target)
        metrics = score_text(text, media_type)
        admission = KnowledgeAdmissionPolicy().assess(
            admission_entry(sample, source_type),
            AcquiredDocument(
                content=content,
                media_type=media_type,
                filename=filename,
                sha256=hashlib.sha256(content).hexdigest(),
            ),
            ParsedDocument(
                title=sample["title"],
                blocks=(ParsedBlock(kind="paragraph", text=text),),
            ),
        )
        fact_candidates = (
            DeterministicKnowledgeFactExtractor().extract(
                (audit_chunk(text),),
                entry=admission_entry(sample, source_type),
            )
            if admission.accepted_for_qdrant
            and admission.extract_structured_facts
            else ()
        )
        result.update(
            {
                "status": "captured",
                "origin": origin,
                "media_type": media_type,
                "filename": str(target.relative_to(ROOT)),
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
                "parser": parser_name,
                "admission_route": admission.route,
                "accepted_for_qdrant": admission.accepted_for_qdrant,
                "admission_reason_codes": list(admission.reason_codes),
                "admission_warnings": list(admission.warnings),
                "fact_candidates": [
                    fact.model_dump(mode="json") for fact in fact_candidates
                ],
                **metrics,
            }
        )
    except Exception as error:  # Keep the audit going when one source rejects automation.
        result.update({"status": "failed", "error": f"{type(error).__name__}: {error}"})
    return result


def cached_audit_sample(
    target_dir: Path,
    sample_id: str,
) -> tuple[bytes, str, str] | None:
    candidates = sorted(
        target_dir.glob(f"{sample_id}.*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None
    source = candidates[0]
    return source.read_bytes(), media_type_for(source), source.name


def acquire(
    sample: dict[str, Any], client: httpx.Client
) -> tuple[bytes, str, str, str]:
    mode = sample["capture_mode"]
    if mode == "local_file":
        source = ROOT / sample["local_path"]
        return source.read_bytes(), media_type_for(source), source.name, "local_file"
    if mode == "sqlite_snapshot":
        content = read_snapshot(int(sample["sqlite_row_id"]))
        return content, "application/json", f"{sample['id']}.json", "runtime_database"

    reuse_glob = sample.get("reuse_glob")
    if reuse_glob:
        candidates = sorted(ROOT.glob(reuse_glob), key=lambda path: path.stat().st_mtime, reverse=True)
        if candidates:
            source = candidates[0]
            return source.read_bytes(), media_type_for(source), source.name, "existing_knowledge_raw"

    chunks: list[bytes] = []
    total = 0
    with client.stream("GET", sample["url"]) as response:
        response.raise_for_status()
        declared_size = int(response.headers.get("content-length", "0") or 0)
        if declared_size > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"declared document size {declared_size} exceeds limit")
        media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        final_url = str(response.url)
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise ValueError(f"document exceeds {MAX_DOWNLOAD_BYTES} bytes")
            chunks.append(chunk)
    content = b"".join(chunks)
    if not media_type or media_type == "application/octet-stream":
        media_type = sniff_media_type(content, final_url)
    filename = Path(httpx.URL(final_url).path).name or f"{sample['id']}{extension_for(media_type)}"
    return content, media_type, filename, "download"


def read_snapshot(row_id: int) -> bytes:
    database = ROOT / "backend/restaurant_agent.db"
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT * FROM external_context_snapshots WHERE id = ?", (row_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"external_context_snapshots row {row_id} not found")
        payload = dict(row)
        for key in ("metrics_json", "evidence_json", "warnings_json"):
            payload[key.removesuffix("_json")] = json.loads(payload.pop(key))
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    finally:
        connection.close()


def extract_text(content: bytes, media_type: str, path: Path) -> tuple[str, str]:
    if media_type == "application/pdf" or content.startswith(b"%PDF"):
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(content)
        pages: list[str] = []
        try:
            for page_index in range(len(pdf)):
                page = pdf[page_index]
                text_page = page.get_textpage()
                pages.append(text_page.get_text_range())
                text_page.close()
                page.close()
        finally:
            pdf.close()
        return normalize_text("\n".join(pages)), "pypdfium2"
    if media_type in {"text/html", "application/xhtml+xml"} or b"<html" in content[:1000].lower():
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(content, "lxml")
        for node in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
            node.decompose()
        scope = next(
            (
                node
                for selector in (".TRS_Editor", "article", ".article_content", "main")
                if (node := soup.select_one(selector)) is not None
                and len(node.get_text(" ", strip=True)) >= 100
            ),
            soup,
        )
        return normalize_text(scope.get_text("\n", strip=True)), "beautifulsoup-lxml"
    if media_type == "application/json" or path.suffix.lower() == ".json":
        value = json.loads(content.decode("utf-8-sig"))
        return normalize_text(json.dumps(value, ensure_ascii=False)), "json"
    if path.suffix.lower() == ".csv":
        rows = list(csv.reader(content.decode("utf-8-sig").splitlines()))
        return normalize_text("\n".join(" | ".join(row) for row in rows)), "csv"
    return normalize_text(content.decode("utf-8-sig", errors="replace")), "plain-text"


def score_text(text: str, media_type: str) -> dict[str, Any]:
    numbers = re.findall(r"(?<!\w)-?\d+(?:\.\d+)?%?", text)
    dates = re.findall(r"(?:20\d{2}[年./-]\d{1,2}(?:[月./-]\d{1,2}日?)?|20\d{2}年)", text)
    currency = re.findall(r"(?:人民币|亿元|万元|元/|港元|美元)", text)
    boilerplate_terms = ("版权所有", "联系我们", "网站地图", "隐私政策", "责任编辑", "分享到")
    noise_hits = sum(text.count(term) for term in boilerplate_terms)
    lines = [line for line in text.splitlines() if line.strip()]
    excerpt = next((line for line in lines if len(line) >= 40), text[:240])[:240]
    char_count = len(text)
    fact_density = round((len(numbers) + len(dates) + len(currency)) * 1000 / max(char_count, 1), 2)
    return {
        "text_chars": char_count,
        "line_count": len(lines),
        "numeric_tokens": len(numbers),
        "date_tokens": len(dates),
        "currency_tokens": len(currency),
        "fact_markers_per_1k_chars": fact_density,
        "noise_hits": noise_hits,
        "has_substantial_text": char_count >= 500,
        "excerpt": excerpt,
        "content_profile": content_profile(media_type, char_count, fact_density, noise_hits),
    }


def content_profile(media_type: str, chars: int, density: float, noise: int) -> str:
    if chars < 200:
        return "empty_or_blocked"
    if media_type in {"application/json", "text/csv"}:
        return "structured"
    if density >= 8 and noise <= 5:
        return "fact_dense"
    if density >= 3:
        return "mixed_evidence"
    return "narrative_or_sparse"


def build_summary(manifest: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    captured = [item for item in results if item["status"] == "captured"]
    real = [item for item in captured if item["sample_kind"].startswith("real_")]
    return {
        "channel_count": len(manifest["channels"]),
        "sample_count": len(results),
        "captured_count": len(captured),
        "failed_count": len(results) - len(captured),
        "real_sample_count": len(real),
        "usable_real_sample_count": sum(
            item["sample_kind"].startswith("real_")
            and item.get("has_substantial_text", False)
            for item in captured
        ),
        "qdrant_admitted_count": sum(
            item.get("accepted_for_qdrant", False) for item in captured
        ),
        "candidate_fact_count": sum(
            len(item.get("fact_candidates", ())) for item in captured
        ),
        "synthetic_fixture_count": sum(
            item["sample_kind"] == "synthetic_contract_fixture" for item in captured
        ),
        "profiles": dict(Counter(item.get("content_profile", "failed") for item in results)),
    }


def render_report(
    manifest: dict[str, Any], results: list[dict[str, Any]], summary: dict[str, Any]
) -> str:
    lines = [
        "# 餐饮知识来源真实样本审计",
        "",
        "> 这是一轮隔离审计，样本尚未自动写入正式 Qdrant。原始文件仅保存在本机 `raw/` 目录。",
        "",
        "## 总览",
        "",
        f"- 渠道：{summary['channel_count']} 个",
        f"- 计划样本：{summary['sample_count']} 份",
        f"- 成功获取：{summary['captured_count']} 份，其中真实来源 {summary['real_sample_count']} 份",
        f"- 可用真实正文：{summary['usable_real_sample_count']} 份（正文不少于 500 字符）",
        f"- 自动准入 Qdrant：{summary['qdrant_admitted_count']} 份",
        f"- 确定性候选事实：{summary['candidate_fact_count']} 条，默认均为 `pending`",
        f"- 获取失败：{summary['failed_count']} 份",
        f"- 模拟契约样本：{summary['synthetic_fixture_count']} 份，不计入真实语料",
        "",
        "## 渠道结论",
        "",
        "| 渠道 | 成功/计划 | 可用真实样本 | Qdrant准入 | 内容效果 | 建议接入方式 |",
        "|---|---:|---:|---|---|",
    ]
    by_channel: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        by_channel.setdefault(result["channel"], []).append(result)
    for channel in manifest["channels"]:
        items = by_channel[channel["channel"]]
        captured = [item for item in items if item["status"] == "captured"]
        real = [
            item
            for item in captured
            if item["sample_kind"].startswith("real_")
            and item.get("has_substantial_text", False)
        ]
        profiles = Counter(item.get("content_profile", "failed") for item in items)
        profile = "、".join(f"{key}×{value}" for key, value in profiles.items())
        admitted = sum(item.get("accepted_for_qdrant", False) for item in captured)
        lines.append(
            f"| {channel['label']} | {len(captured)}/{len(items)} | {len(real)} | {admitted} | {profile} | `{channel['recommended_role']}` |"
        )

    lines.extend(["", "## 样本明细", ""])
    for channel in manifest["channels"]:
        lines.extend([f"### {channel['label']}", ""])
        for item in by_channel[channel["channel"]]:
            lines.append(f"#### {item['title']}")
            lines.append("")
            lines.append(f"- 状态：`{item['status']}`；类型：`{item['sample_kind']}`；获取：`{item['capture_mode']}`")
            lines.append(
                f"- 准入：`{item['source_type']}` → `{item['admission_route']}`；Qdrant：`{item['accepted_for_qdrant']}`"
            )
            if item.get("admission_reason_codes"):
                lines.append(
                    f"- 准入原因：`{', '.join(item['admission_reason_codes'])}`"
                )
            if item.get("fact_candidates"):
                rendered_facts = "；".join(
                    f"{fact['label']}={fact['value']} {fact['unit']}"
                    for fact in item["fact_candidates"]
                )
                lines.append(f"- 候选事实：{rendered_facts}")
            if item.get("url"):
                lines.append(f"- 原始链接：{item['url']}")
            if item["status"] == "captured":
                lines.append(
                    f"- 解析：`{item['parser']}`；正文 {item['text_chars']} 字符；数字标记 {item['numeric_tokens']}；事实标记密度 {item['fact_markers_per_1k_chars']}/千字；噪声命中 {item['noise_hits']}"
                )
                lines.append(f"- 本地文件：`{item['filename']}`")
                lines.append(f"- 内容切片：{item['excerpt']}")
            else:
                lines.append(f"- 失败原因：`{item.get('error', 'unknown')}`")
            if item.get("limitations"):
                lines.append(f"- 限制：{item['limitations']}")
            lines.append("")

    lines.extend(
        [
            "## 初步准入规则",
            "",
            "1. 国家与城市统计优先抽取成结构化事实，正文 RAG 仅保留口径说明和上下文。",
            "2. 法规按生效日期、效力层级和适用范围建索引；标准全文受限时只存元数据与官方链接。",
            "3. 招股书和品牌材料必须标记利益相关方，不能单独外推行业结论。",
            "4. 地图 POI、门店评论和招聘职位属于时效型数据，应通过工具实时查询并设置过期时间，不做长期静态语料。",
            "5. 商户经营 CSV 必须来自授权上传、脱敏并按项目隔离；当前模拟文件只验证字段契约。",
            "6. 新闻用于发现趋势和定位原始出处，模型给出经营结论前应回溯统计、披露或平台原始数据。",
            "",
        ]
    )
    return "\n".join(lines)


def admission_entry(sample: dict[str, Any], source_type: str) -> KnowledgeManifestEntry:
    canonical_url = sample.get("url") or "https://local.market-pilot.invalid/source"
    return KnowledgeManifestEntry(
        source=KnowledgeSourceInput(
            source_key=sample["id"],
            title=sample["title"],
            publisher=sample["publisher"],
            source_type=source_type,
            canonical_url=canonical_url,
            reliability_tier=reliability_tier(source_type),
        ),
        acquisition=KnowledgeAcquisition(
            local_path="source.bin",
            allowed_media_types=("application/octet-stream",),
        ),
        fact_status="observed",
    )


def audit_chunk(text: str) -> KnowledgeChunk:
    return KnowledgeChunk(
        point_id="00000000-0000-0000-0000-000000000001",
        chunk_id="audit-c0000",
        document_version_id=1,
        chunk_index=0,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        raw_text=text,
        retrieval_text=text,
        payload={},
    )


def formal_source_type(channel: str, sample: dict[str, Any]) -> str:
    if channel in {"national_statistics", "city_statistics"}:
        return "government_statistics"
    if channel == "regulation_and_standards":
        return "standard_metadata" if "standard" in sample["id"] else "regulation"
    if channel == "exchange_disclosure":
        return "listed_company_filing"
    if channel == "industry_association":
        return "industry_association"
    if channel == "map_platform":
        return "map_platform"
    if channel == "brand_official":
        return "brand_official"
    if channel == "academic_research":
        return "academic_research"
    if channel == "commercial_property":
        return "commercial_property"
    if channel == "recruitment_and_labor":
        return "government_statistics"
    if channel == "news_media":
        return "news_media"
    if channel == "reviews_and_social":
        return (
            "government_statistics"
            if sample["publisher"] == "国家市场监督管理总局"
            else "industry_report"
        )
    if channel == "merchant_uploaded":
        return "merchant_operating_data"
    if channel == "internal_methodology":
        return "internal_methodology"
    return "unknown"


def reliability_tier(source_type: str) -> int:
    if source_type in {"government_statistics", "official_statistics", "regulation", "standard_metadata", "internal_methodology"}:
        return 1
    if source_type in {"listed_company_filing", "industry_association", "academic_research", "commercial_property"}:
        return 2
    return 3


def normalize_text(value: str) -> str:
    lines = [" ".join(line.split()) for line in value.replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line).strip()


def media_type_for(path: Path) -> str:
    return {
        ".pdf": "application/pdf",
        ".html": "text/html",
        ".htm": "text/html",
        ".json": "application/json",
        ".csv": "text/csv",
        ".md": "text/markdown",
        ".txt": "text/plain",
    }.get(path.suffix.lower(), "application/octet-stream")


def sniff_media_type(content: bytes, url: str) -> str:
    if content.startswith(b"%PDF"):
        return "application/pdf"
    if content.lstrip().startswith((b"{", b"[")):
        return "application/json"
    if b"<html" in content[:1000].lower() or url.lower().endswith((".html", ".htm")):
        return "text/html"
    return "application/octet-stream"


def extension_for(media_type: str) -> str:
    return {
        "application/pdf": ".pdf",
        "application/json": ".json",
        "text/html": ".html",
        "text/csv": ".csv",
        "text/markdown": ".md",
        "text/plain": ".txt",
    }.get(media_type, ".bin")


if __name__ == "__main__":
    main()
