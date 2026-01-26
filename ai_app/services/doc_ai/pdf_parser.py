"""PDF 파서 - PDF 파일에서 텍스트와 레이아웃 추출"""

import io
from dataclasses import dataclass
from pathlib import Path

import pymupdf


@dataclass
class TextBlock:
    """위치 정보를 포함한 텍스트 블록"""

    text: str
    x0: float  # 좌측 x 좌표
    y0: float  # 상단 y 좌표
    x1: float  # 우측 x 좌표
    y1: float  # 하단 y 좌표
    page_num: int  # 페이지 번호

    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            "text": self.text,
            "bbox": [self.x0, self.y0, self.x1, self.y1],
            "page": self.page_num,
        }


@dataclass
class ParsedPage:
    """파싱된 PDF 페이지"""

    page_num: int  # 페이지 번호 (0부터 시작)
    width: float  # 페이지 너비
    height: float  # 페이지 높이
    text_blocks: list[TextBlock]  # 텍스트 블록 목록
    full_text: str  # 전체 텍스트


@dataclass
class ParsedDocument:
    """파싱된 PDF 문서 전체"""

    pages: list[ParsedPage]  # 페이지 목록
    total_pages: int  # 총 페이지 수
    full_text: str  # 전체 텍스트
    text_blocks: list[TextBlock]  # 모든 텍스트 블록
    is_text_pdf: bool  # True: 텍스트 기반 PDF, False: 이미지 기반 (OCR 필요)


class PDFParser:
    """PDF 텍스트 추출 및 레이아웃 정보 파서"""

    def __init__(self, min_text_length: int = 50):
        """
        PDF 파서 초기화

        Args:
            min_text_length: 텍스트 기반 PDF로 판단하는 최소 텍스트 길이
        """
        self.min_text_length = min_text_length

    def parse(self, file_path: str | Path) -> ParsedDocument:
        """
        PDF 파일을 파싱하여 텍스트와 레이아웃 추출

        Args:
            file_path: PDF 파일 경로

        Returns:
            ParsedDocument: 추출된 내용
        """
        doc = pymupdf.open(str(file_path))
        return self._process_document(doc)

    def parse_bytes(self, pdf_bytes: bytes) -> ParsedDocument:
        """
        바이트 데이터로 PDF 파싱

        Args:
            pdf_bytes: PDF 파일 바이트 데이터

        Returns:
            ParsedDocument: 추출된 내용
        """
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        return self._process_document(doc)

    def _process_document(self, doc: pymupdf.Document) -> ParsedDocument:
        """pymupdf 문서 처리"""
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
        # 추출된 텍스트 길이로 텍스트 기반 PDF 여부 판단
        is_text_pdf = len(full_text.strip()) >= self.min_text_length

        return ParsedDocument(
            pages=pages,
            total_pages=len(pages),
            full_text=full_text,
            text_blocks=all_text_blocks,
            is_text_pdf=is_text_pdf,
        )

    def _parse_page(self, page: pymupdf.Page, page_num: int) -> ParsedPage:
        """단일 페이지 파싱"""
        text_blocks: list[TextBlock] = []
        rect = page.rect

        # "dict" 포맷으로 상세 블록 정보와 함께 텍스트 추출
        blocks = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)["blocks"]

        for block in blocks:
            if block.get("type") == 0:  # 텍스트 블록인 경우
                block_text_parts = []

                # 라인별로 텍스트 수집
                for line in block.get("lines", []):
                    line_text = ""
                    for span in line.get("spans", []):
                        line_text += span.get("text", "")
                    block_text_parts.append(line_text)

                block_text = "\n".join(block_text_parts).strip()
                if block_text:
                    bbox = block["bbox"]  # 바운딩 박스 좌표
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

        # 읽기 순서를 유지한 전체 페이지 텍스트
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
        LLM 컨텍스트용 레이아웃 힌트가 포함된 텍스트 생성

        Args:
            parsed_doc: 파싱된 문서

        Returns:
            레이아웃 마커가 포함된 텍스트
        """
        result_parts = []

        for page in parsed_doc.pages:
            result_parts.append(f"=== 페이지 {page.page_num + 1} ===")

            # 위치 기준으로 블록 정렬 (위에서 아래로, 왼쪽에서 오른쪽으로)
            sorted_blocks = sorted(
                page.text_blocks,
                key=lambda b: (b.y0, b.x0),
            )

            for block in sorted_blocks:
                result_parts.append(block.text)

            result_parts.append("")

        return "\n".join(result_parts)
