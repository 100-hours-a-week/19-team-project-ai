"""이미지 기반 PDF 처리 - VLM OCR + PII 탐지 파이프라인"""

import asyncio
import logging

import pymupdf
from google.genai import types
from pydantic import BaseModel, Field

from adapters.llm_client import LLMClient, get_llm_client
from prompts import get_vlm_ocr_pii_prompts
from services.doc_ai.pdf_parser import ParsedDocument, ParsedPage, TextBlock
from services.doc_ai.pii_masker import MaskingResult, PIIEntity, PIIMasker, get_pii_masker

logger = logging.getLogger(__name__)

# 200 DPI 변환 매트릭스
DPI_MATRIX = pymupdf.Matrix(200 / 72, 200 / 72)

# VLM 동시 호출 제한
MAX_CONCURRENT_VLM = 3

# PII 타입 → 마스킹 라벨 매핑
PII_MASK_LABELS = {
    "NAME": "[이름]",
    "PHONE": "[전화번호]",
    "EMAIL": "[이메일]",
    "RRN": "[주민번호]",
    "ADDRESS": "[주소]",
}


class VLMPIIEntity(BaseModel):
    """VLM이 감지한 PII 엔티티"""

    text: str = Field(description="PII 원본 텍스트")
    type: str = Field(description="PII 유형: NAME, PHONE, EMAIL, RRN, ADDRESS")


class VLMOCRResult(BaseModel):
    """VLM OCR + PII 탐지 결과"""

    ocr_text: str = Field(description="추출된 전체 텍스트")
    pii_entities: list[VLMPIIEntity] = Field(default_factory=list, description="감지된 PII 목록")


class ImagePDFProcessor:
    """이미지 기반 PDF를 VLM OCR + PII 탐지로 처리"""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        pii_masker: PIIMasker | None = None,
    ):
        self._llm_client = llm_client
        self._pii_masker = pii_masker
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_VLM)

    @property
    def llm_client(self) -> LLMClient:
        if self._llm_client is None:
            self._llm_client = get_llm_client()
        return self._llm_client

    @property
    def pii_masker(self) -> PIIMasker:
        if self._pii_masker is None:
            self._pii_masker = get_pii_masker()
        return self._pii_masker

    def convert_pages_to_images(self, doc: pymupdf.Document) -> list[bytes]:
        """PDF 페이지를 PNG 이미지 바이트 리스트로 변환 (200 DPI)"""
        images = []
        for page in doc:
            pixmap = page.get_pixmap(matrix=DPI_MATRIX)
            images.append(pixmap.tobytes("png"))
        return images

    async def ocr_and_detect_pii(self, page_image: bytes) -> VLMOCRResult:
        """단일 페이지 이미지에서 OCR + PII 탐지 (Gemini Vision)"""
        system_prompt, user_prompt = get_vlm_ocr_pii_prompts()

        contents = [
            types.Part.from_bytes(data=page_image, mime_type="image/png"),
            types.Part.from_text(text=user_prompt),
        ]

        async with self._semaphore:
            raw = await self.llm_client.generate_json_with_images(
                contents=contents,
                system_instruction=system_prompt,
                response_schema=VLMOCRResult,
                temperature=0.1,
            )

        return VLMOCRResult.model_validate(raw)

    async def process(
        self,
        pdf_bytes: bytes,
        extract_pii: bool = False,
    ) -> tuple[ParsedDocument, MaskingResult]:
        """
        이미지 기반 PDF 전체 처리 파이프라인

        Args:
            pdf_bytes: PDF 바이트 데이터
            extract_pii: True면 PII 원문 유지, False면 마스킹 적용

        Returns:
            (ParsedDocument, MaskingResult) 튜플
        """
        # 1. PDF → 페이지별 PNG 이미지
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        page_images = self.convert_pages_to_images(doc)
        total_pages = len(page_images)
        logger.info(f"이미지 PDF {total_pages}페이지 변환 완료")

        # 페이지 메타데이터 수집 (ParsedPage 구성용)
        page_metas = []
        for page in doc:
            rect = page.rect
            page_metas.append((rect.width, rect.height))
        doc.close()

        # 2. 페이지별 VLM OCR + PII 탐지 (동시 실행)
        tasks = [self.ocr_and_detect_pii(img) for img in page_images]
        vlm_results: list[VLMOCRResult] = await asyncio.gather(*tasks)

        # 3. 페이지 텍스트 합산 + VLM PII 엔티티 수집 (오프셋 보정)
        all_text_parts: list[str] = []
        all_vlm_entities: list[VLMPIIEntity] = []
        current_offset = 0

        for i, result in enumerate(vlm_results):
            page_text = result.ocr_text
            all_text_parts.append(page_text)

            for entity in result.pii_entities:
                all_vlm_entities.append(entity)

            # 다음 페이지 오프셋: 현재 텍스트 + "\n\n" 구분자
            current_offset += len(page_text) + 2

        full_text = "\n\n".join(all_text_parts)
        logger.info(f"VLM OCR 완료: {len(full_text)}자, PII {len(all_vlm_entities)}개 감지")

        # 4. PII 마스킹 적용
        if extract_pii:
            # PII 포함 모드: 마스킹 없이 원문 반환
            masked_text = full_text
            masking_result = MaskingResult(
                masked_text=full_text,
                entities=[],
                processing_time=0.0,
                method_name="VLM OCR (PII 포함)",
            )
        else:
            # 1차: VLM PII로 텍스트 치환
            masked_text, vlm_pii_entities = self._apply_pii_masking(full_text, all_vlm_entities)
            logger.debug(f"1차 VLM PII 마스킹: {len(vlm_pii_entities)}개 치환")

            # 2차: 기존 Presidio/KcBERT로 추가 감지
            secondary_result = self.pii_masker.mask_text(masked_text)
            masked_text = secondary_result.masked_text
            logger.debug(f"2차 텍스트 PII 마스킹: {len(secondary_result.entities)}개 추가 감지")

            # 통합 결과
            all_pii_entities = vlm_pii_entities + secondary_result.entities
            masking_result = MaskingResult(
                masked_text=masked_text,
                entities=all_pii_entities,
                processing_time=secondary_result.processing_time,
                method_name=f"VLM + {secondary_result.method_name}",
            )

        # 5. ParsedDocument 구성
        pages: list[ParsedPage] = []
        for i, page_text in enumerate(all_text_parts):
            width, height = page_metas[i]
            text_block = TextBlock(
                text=page_text,
                x0=0,
                y0=0,
                x1=width,
                y1=height,
                page_num=i,
            )
            pages.append(
                ParsedPage(
                    page_num=i,
                    width=width,
                    height=height,
                    text_blocks=[text_block],
                    full_text=page_text,
                )
            )

        parsed_doc = ParsedDocument(
            pages=pages,
            total_pages=total_pages,
            full_text=masked_text,
            text_blocks=[tb for p in pages for tb in p.text_blocks],
            is_text_pdf=True,  # OCR 처리 완료 → 텍스트로 간주
        )

        return parsed_doc, masking_result

    def _apply_pii_masking(
        self,
        text: str,
        entities: list[VLMPIIEntity],
    ) -> tuple[str, list[PIIEntity]]:
        """VLM PII 엔티티로 텍스트 치환 (긴 텍스트부터 치환하여 부분 매칭 방지)"""
        masked_text = text
        pii_entities: list[PIIEntity] = []

        # 긴 텍스트부터 치환 (부분 매칭 충돌 방지)
        sorted_entities = sorted(entities, key=lambda e: len(e.text), reverse=True)

        for entity in sorted_entities:
            label = PII_MASK_LABELS.get(entity.type, f"[{entity.type}]")
            # 텍스트 내 모든 출현 위치를 찾아 치환
            start = 0
            while True:
                idx = masked_text.find(entity.text, start)
                if idx == -1:
                    break
                pii_entities.append(
                    PIIEntity(
                        entity_type=entity.type,
                        start=idx,
                        end=idx + len(entity.text),
                        original_text=entity.text,
                        masked_text=label,
                    )
                )
                masked_text = masked_text[:idx] + label + masked_text[idx + len(entity.text) :]
                start = idx + len(label)

        return masked_text, pii_entities
