"""PDF Parser - Extract text and layout from PDF files."""

import io
from dataclasses import dataclass
from pathlib import Path

import pymupdf


@dataclass
class TextBlock:
    """Represents a text block with position info."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page_num: int

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "bbox": [self.x0, self.y0, self.x1, self.y1],
            "page": self.page_num,
        }


@dataclass
class ParsedPage:
    """Represents a parsed PDF page."""

    page_num: int
    width: float
    height: float
    text_blocks: list[TextBlock]
    full_text: str


@dataclass
class ParsedDocument:
    """Complete parsed PDF document."""

    pages: list[ParsedPage]
    total_pages: int
    full_text: str
    text_blocks: list[TextBlock]
    is_text_pdf: bool  # True if text-based, False if image-based (needs OCR)


class PDFParser:
    """PDF text extraction with layout information."""

    def __init__(self, min_text_length: int = 50):
        """
        Initialize PDF parser.

        Args:
            min_text_length: Minimum text length to consider PDF as text-based
        """
        self.min_text_length = min_text_length

    def parse(self, file_path: str | Path) -> ParsedDocument:
        """
        Parse a PDF file and extract text with layout.

        Args:
            file_path: Path to PDF file

        Returns:
            ParsedDocument with extracted content
        """
        doc = pymupdf.open(str(file_path))
        return self._process_document(doc)

    def parse_bytes(self, pdf_bytes: bytes) -> ParsedDocument:
        """
        Parse PDF from bytes.

        Args:
            pdf_bytes: PDF file content as bytes

        Returns:
            ParsedDocument with extracted content
        """
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        return self._process_document(doc)

    def _process_document(self, doc: pymupdf.Document) -> ParsedDocument:
        """Process pymupdf document."""
        pages: list[ParsedPage] = []
        all_text_blocks: list[TextBlock] = []
        all_text_parts: list[str] = []

        for page_num, page in enumerate(doc):
            parsed_page = self._parse_page(page, page_num)
            pages.append(parsed_page)
            all_text_blocks.extend(parsed_page.text_blocks)
            all_text_parts.append(parsed_page.full_text)

        doc.close()

        full_text = "\n\n".join(all_text_parts)
        is_text_pdf = len(full_text.strip()) >= self.min_text_length

        return ParsedDocument(
            pages=pages,
            total_pages=len(pages),
            full_text=full_text,
            text_blocks=all_text_blocks,
            is_text_pdf=is_text_pdf,
        )

    def _parse_page(self, page: pymupdf.Page, page_num: int) -> ParsedPage:
        """Parse a single page."""
        text_blocks: list[TextBlock] = []
        rect = page.rect

        # Extract text with position using "dict" format for detailed block info
        blocks = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)["blocks"]

        for block in blocks:
            if block.get("type") == 0:  # Text block
                block_text_parts = []

                for line in block.get("lines", []):
                    line_text = ""
                    for span in line.get("spans", []):
                        line_text += span.get("text", "")
                    block_text_parts.append(line_text)

                block_text = "\n".join(block_text_parts).strip()
                if block_text:
                    bbox = block["bbox"]
                    text_blocks.append(
                        TextBlock(
                            text=block_text,
                            x0=bbox[0],
                            y0=bbox[1],
                            x1=bbox[2],
                            y1=bbox[3],
                            page_num=page_num,
                        )
                    )

        # Get full page text (preserving reading order)
        full_text = page.get_text("text")

        return ParsedPage(
            page_num=page_num,
            width=rect.width,
            height=rect.height,
            text_blocks=text_blocks,
            full_text=full_text,
        )

    def get_text_with_layout(self, parsed_doc: ParsedDocument) -> str:
        """
        Format text with layout hints for LLM context.

        Args:
            parsed_doc: Parsed document

        Returns:
            Text with layout markers
        """
        result_parts = []

        for page in parsed_doc.pages:
            result_parts.append(f"=== Page {page.page_num + 1} ===")

            # Sort blocks by position (top to bottom, left to right)
            sorted_blocks = sorted(
                page.text_blocks,
                key=lambda b: (b.y0, b.x0),
            )

            for block in sorted_blocks:
                result_parts.append(block.text)

            result_parts.append("")

        return "\n".join(result_parts)
