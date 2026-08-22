from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Protocol

from app.knowledge.document import AcquiredDocument, ParsedBlock, ParsedDocument


class KnowledgeParseError(ValueError):
    pass


class DocumentParser(Protocol):
    version: str

    def parse(self, document: AcquiredDocument, *, title: str) -> ParsedDocument: ...


class MarkdownDocumentParser:
    version = "markdown-structured-v1"

    def parse(self, document: AcquiredDocument, *, title: str) -> ParsedDocument:
        if document.media_type not in {"text/markdown", "text/plain"}:
            raise KnowledgeParseError(
                f"built-in parser does not support {document.media_type}"
            )
        try:
            text = document.content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise KnowledgeParseError("document is not valid UTF-8") from error
        blocks = _parse_markdown_blocks(text)
        if not blocks:
            raise KnowledgeParseError("document contains no indexable text")
        return ParsedDocument(title=title, blocks=tuple(blocks))


class DoclingDocumentParser:
    version = "docling-v2-markdown-v2"

    def __init__(self) -> None:
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as error:
            raise KnowledgeParseError(
                "Docling is required for PDF, DOCX, and HTML ingestion"
            ) from error
        self._converter = DocumentConverter()
        self._markdown = MarkdownDocumentParser()

    def parse(self, document: AcquiredDocument, *, title: str) -> ParsedDocument:
        suffix = _docling_suffix(document)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                handle.write(document.content)
                handle.flush()
                temporary_path = Path(handle.name)
            result = self._converter.convert(str(temporary_path))
            markdown = result.document.export_to_markdown()
        except Exception as error:
            raise KnowledgeParseError("Docling failed to parse document") from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        normalized = AcquiredDocument(
            content=markdown.encode("utf-8"),
            media_type="text/markdown",
            filename=f"{Path(document.filename).stem}.md",
            sha256=document.sha256,
        )
        parsed = self._markdown.parse(normalized, title=title)
        if document.media_type != "text/html":
            return parsed
        cleaned = tuple(
            block.model_copy(
                update={
                    "heading_path": tuple(
                        heading
                        for heading in block.heading_path
                        if heading.strip() not in {"下载和关注", "Download and follow"}
                    )
                }
            )
            for block in parsed.blocks
            if not _is_html_boilerplate(block.text)
        )
        if not cleaned:
            raise KnowledgeParseError("document contains no indexable text")
        return parsed.model_copy(update={"blocks": cleaned})


class DocumentParserRouter:
    def __init__(
        self,
        *,
        markdown_parser: DocumentParser | None = None,
        docling_factory=None,
    ) -> None:
        self._markdown = markdown_parser or MarkdownDocumentParser()
        self._docling_factory = docling_factory or DoclingDocumentParser

    @property
    def version(self) -> str:
        return "router-v1"

    def parse(self, document: AcquiredDocument, *, title: str) -> ParsedDocument:
        if document.media_type in {"text/markdown", "text/plain"}:
            return self._markdown.parse(document, title=title)
        return self._docling_factory().parse(document, title=title)


def _parse_markdown_blocks(text: str) -> list[ParsedBlock]:
    heading_path: list[str] = []
    blocks: list[ParsedBlock] = []
    paragraph: list[str] = []
    table: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            value = " ".join(item.strip() for item in paragraph if item.strip())
            paragraph.clear()
            if value:
                blocks.append(
                    ParsedBlock(
                        kind="paragraph",
                        text=value,
                        heading_path=tuple(heading_path),
                    )
                )

    def flush_table() -> None:
        if table:
            value = "\n".join(table)
            table.clear()
            blocks.append(
                ParsedBlock(
                    kind="table",
                    text=value,
                    heading_path=tuple(heading_path),
                )
            )

    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            flush_table()
            level = len(heading.group(1))
            heading_path[level - 1 :] = [heading.group(2).strip()]
            continue
        if line.startswith("|") and line.endswith("|"):
            flush_paragraph()
            table.append(line)
            continue
        flush_table()
        list_item = re.match(r"^(?:[-*+] |\d+[.)] )(.+)$", line)
        if list_item:
            flush_paragraph()
            blocks.append(
                ParsedBlock(
                    kind="list_item",
                    text=list_item.group(1).strip(),
                    heading_path=tuple(heading_path),
                )
            )
        elif line:
            paragraph.append(line)
        else:
            flush_paragraph()
    flush_paragraph()
    flush_table()
    return blocks


def _docling_suffix(document: AcquiredDocument) -> str:
    known = {
        "application/pdf": ".pdf",
        (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ): ".docx",
        "text/html": ".html",
    }
    return known.get(document.media_type, Path(document.filename).suffix or ".bin")


def _is_html_boilerplate(text: str) -> bool:
    normalized = " ".join(text.split()).strip()
    if normalized.lower() in {
        "img",
        "image",
        "english version",
        "简体中文 / 繁體中文",
        "简体中文/繁體中文",
    }:
        return True
    links = re.findall(r"\[[^\]]+\]\([^)]+\)", normalized)
    if not links:
        return False
    residual = re.sub(r"\[[^\]]+\]\([^)]+\)", "", normalized)
    residual = re.sub(r"[\\|*/\s-]+", "", residual)
    return len(residual) < 8
