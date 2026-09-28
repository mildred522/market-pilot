from __future__ import annotations

import hashlib
import re
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from app.knowledge.document import AcquiredDocument, ParsedBlock, ParsedDocument


DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD_NS = {"w": WORD_NAMESPACE}


class KnowledgeParseError(ValueError):
    pass


class PdfRequiresOcrError(KnowledgeParseError):
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


class PdfTextDocumentParser:
    """Extract searchable page text without requiring Docling model assets."""

    version = "pdfium-structured-v2"

    def parse(self, document: AcquiredDocument, *, title: str) -> ParsedDocument:
        if document.media_type != "application/pdf":
            raise KnowledgeParseError("PDF text parser requires application/pdf")
        try:
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(BytesIO(document.content))
            blocks = []
            try:
                for page_index in range(len(pdf)):
                    page = pdf[page_index]
                    text_page = page.get_textpage()
                    try:
                        page_text = text_page.get_text_range()
                    finally:
                        text_page.close()
                        page.close()
                    blocks.extend(
                        _parse_pdf_page_blocks(page_text, page_number=page_index + 1)
                    )
            finally:
                pdf.close()
        except Exception as error:
            raise KnowledgeParseError("PDF text extraction failed") from error
        if not blocks:
            raise PdfRequiresOcrError(
                "PDF contains no extractable text; OCR or a text-layer copy is required"
            )
        return ParsedDocument(title=title, blocks=tuple(blocks))


class HtmlDocumentParser:
    """Parse ordinary article HTML while preserving semantic headings."""

    version = "html-structured-v2"

    def parse(self, document: AcquiredDocument, *, title: str) -> ParsedDocument:
        if document.media_type != "text/html":
            raise KnowledgeParseError("HTML parser requires text/html")
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(document.content, "lxml")
        except Exception as error:
            raise KnowledgeParseError("HTML parsing failed") from error
        for node in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
            node.decompose()
        scope = soup
        for selector in (".TRS_Editor", "article", ".article_content", "main"):
            candidate = soup.select_one(selector)
            if candidate is not None and len(candidate.get_text(" ", strip=True)) >= 100:
                scope = candidate
                break
        heading_path: list[str] = []
        blocks: list[ParsedBlock] = []
        for node in scope.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"]):
            text = _normalize_extracted_text(node.get_text(" ", strip=True))
            if not text or _is_html_boilerplate(text):
                continue
            if node.name and node.name.startswith("h"):
                level = int(node.name[1])
                heading_path[level - 1 :] = [text]
                continue
            kind = "table" if node.name == "table" else ("list_item" if node.name == "li" else "paragraph")
            blocks.append(
                ParsedBlock(kind=kind, text=text, heading_path=tuple(heading_path))
            )
        if not blocks:
            raise KnowledgeParseError("HTML contains no indexable text")
        return ParsedDocument(title=title, blocks=tuple(blocks))


class DocxDocumentParser:
    """Parse ordinary Word paragraphs and tables without external model assets."""

    version = "docx-structured-v1"

    def parse(self, document: AcquiredDocument, *, title: str) -> ParsedDocument:
        if document.media_type != DOCX_MEDIA_TYPE:
            raise KnowledgeParseError("DOCX parser requires Word Open XML content")
        try:
            with ZipFile(BytesIO(document.content)) as archive:
                document_xml = archive.read("word/document.xml")
            root = ElementTree.fromstring(document_xml)
        except (BadZipFile, KeyError, ElementTree.ParseError) as error:
            raise KnowledgeParseError("DOCX package is invalid") from error

        body = root.find("w:body", WORD_NS)
        if body is None:
            raise KnowledgeParseError("DOCX contains no document body")
        heading_path: list[str] = []
        blocks: list[ParsedBlock] = []
        for element in body:
            if element.tag == _word_tag("p"):
                text = _docx_text(element)
                if not text:
                    continue
                heading_level = _docx_heading_level(element)
                if heading_level is not None:
                    heading_path[heading_level - 1 :] = [text]
                    continue
                kind = (
                    "list_item"
                    if element.find("w:pPr/w:numPr", WORD_NS) is not None
                    else "paragraph"
                )
                blocks.append(
                    ParsedBlock(
                        kind=kind,
                        text=text,
                        heading_path=tuple(heading_path),
                    )
                )
            elif element.tag == _word_tag("tbl"):
                table_text = _docx_table_text(element)
                if table_text:
                    blocks.append(
                        ParsedBlock(
                            kind="table",
                            text=table_text,
                            heading_path=tuple(heading_path),
                        )
                    )
        if not blocks:
            raise KnowledgeParseError("DOCX contains no indexable text")
        return ParsedDocument(title=title, blocks=tuple(blocks))


class DoclingDocumentParser:
    version = "docling-v2-markdown-v2"

    def __init__(self) -> None:
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as error:
            raise KnowledgeParseError(
                "Docling is required for this complex or unsupported document"
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
        pdf_parser: DocumentParser | None = None,
        html_parser: DocumentParser | None = None,
        docx_parser: DocumentParser | None = None,
        docling_factory=None,
    ) -> None:
        self._markdown = markdown_parser or MarkdownDocumentParser()
        self._pdf = pdf_parser or PdfTextDocumentParser()
        self._html = html_parser or HtmlDocumentParser()
        self._docx = docx_parser or DocxDocumentParser()
        self._docling_factory = docling_factory or DoclingDocumentParser

    @property
    def version(self) -> str:
        child_versions = "\n".join(
            (
                self._markdown.version,
                self._pdf.version,
                self._html.version,
                self._docx.version,
                DoclingDocumentParser.version,
            )
        )
        digest = hashlib.sha256(child_versions.encode("utf-8")).hexdigest()[:16]
        return f"router-v2-{digest}"

    def parse(self, document: AcquiredDocument, *, title: str) -> ParsedDocument:
        if document.media_type in {"text/markdown", "text/plain"}:
            return self._markdown.parse(document, title=title)
        if document.media_type == "application/pdf":
            return self._pdf.parse(document, title=title)
        if document.media_type == "text/html":
            return self._html.parse(document, title=title)
        if document.media_type == DOCX_MEDIA_TYPE:
            return self._docx.parse(document, title=title)
        return self._docling_factory().parse(document, title=title)


def _normalize_extracted_text(value: str) -> str:
    lines = [" ".join(line.split()) for line in value.replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _parse_pdf_page_blocks(
    value: str,
    *,
    page_number: int,
) -> list[ParsedBlock]:
    lines = [
        normalized
        for line in value.replace("\r", "\n").split("\n")
        if (normalized := " ".join(line.split()))
    ]
    grouped: list[tuple[str, list[str]]] = []
    for line in lines:
        kind = "table" if _looks_like_pdf_table_row(line) else "paragraph"
        if grouped and grouped[-1][0] == kind:
            grouped[-1][1].append(line)
        else:
            grouped.append((kind, [line]))
    return [
        ParsedBlock(
            kind=kind,
            text="\n".join(group),
            page_start=page_number,
            page_end=page_number,
        )
        for kind, group in grouped
        if group
    ]


def _looks_like_pdf_table_row(value: str) -> bool:
    numbers = re.findall(r"(?<![A-Za-z])[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?", value)
    if len(numbers) < 3:
        return False
    prose_markers = len(re.findall(r"[。！？]", value))
    return prose_markers == 0


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


def _word_tag(local_name: str) -> str:
    return f"{{{WORD_NAMESPACE}}}{local_name}"


def _docx_text(element: ElementTree.Element) -> str:
    value = "".join(
        node.text or "" for node in element.findall(".//w:t", WORD_NS)
    )
    return " ".join(value.split()).strip()


def _docx_heading_level(paragraph: ElementTree.Element) -> int | None:
    style = paragraph.find("w:pPr/w:pStyle", WORD_NS)
    if style is None:
        return None
    value = style.get(_word_tag("val"), "").strip()
    match = re.fullmatch(r"(?:Heading|标题)\s*([1-6])", value, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _docx_table_text(table: ElementTree.Element) -> str:
    rows: list[str] = []
    for row in table.findall("w:tr", WORD_NS):
        cells = [
            _docx_text(cell).replace("|", "\\|")
            for cell in row.findall("w:tc", WORD_NS)
        ]
        if any(cells):
            rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def _docling_suffix(document: AcquiredDocument) -> str:
    known = {
        "application/pdf": ".pdf",
        DOCX_MEDIA_TYPE: ".docx",
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
