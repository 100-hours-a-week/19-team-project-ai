"""파싱 파이프라인 - 이력서 파싱 워크플로우 조율"""

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field
from schemas.resumes import Project, WorkExperience

from opentelemetry import trace
from services.doc_ai.field_extractor import FieldExtractor
from services.doc_ai.pdf_parser import PDFParser
from services.doc_ai.pii_masker import PIIMasker, get_pii_masker

# 로거 설정
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


# ============== LLM 추출 결과 스키마 ==============


class ExtractedFields(BaseModel):
    """추출된 이력서 필드 전체"""

    title: str | None = Field(default=None, description="이력서 제목 (15자 이내)")
    work_experience: list[WorkExperience] = Field(default_factory=list, description="경력")
    projects: list[Project] = Field(default_factory=list, description="프로젝트")
    education: list[str] = Field(default_factory=list, description="학력 (OO대학교 졸업)")
    awards: list[str] = Field(default_factory=list, description="수상 내역")
    certifications: list[str] = Field(default_factory=list, description="자격증 (자격증명 (YYYY))")
    etc: list[str] = Field(default_factory=list, description="대외 활동/기타")


# ============== 파싱 결과 ==============


@dataclass
class ParseResult:
    """파싱 파이프라인 결과"""

    success: bool
    extracted_fields: ExtractedFields | None
    raw_text: str | None
    confidence_score: float | None
    error_message: str | None
    processing_time_ms: int
    model_used: str | None
    needs_ocr: bool


class ParsePipeline:
    """
    이력서 파싱 워크플로우 조율

    파이프라인 단계:
    1. PDF 텍스트 추출 (pdf_parser)
    1-a. 이미지 PDF인 경우 → VLM OCR + PII 처리 (image_pdf_processor)
    2. Presidio PII 마스킹 (pii_masker) - LLM 호출 전
    3. LLM을 통한 필드 추출 (field_extractor)
    4. 스키마 정규화
    """

    def __init__(
        self,
        pdf_parser: PDFParser | None = None,
        field_extractor: FieldExtractor | None = None,
        pii_masker: PIIMasker | None = None,
    ):
        self.pdf_parser = pdf_parser or PDFParser()
        self.field_extractor = field_extractor or FieldExtractor()
        self.pii_masker = pii_masker or get_pii_masker()
        self._image_processor = None

    def _get_image_processor(self):
        """ImagePDFProcessor 지연 초기화"""
        if self._image_processor is None:
            from services.doc_ai.image_pdf_processor import ImagePDFProcessor

            self._image_processor = ImagePDFProcessor(pii_masker=self.pii_masker)
        return self._image_processor

    async def parse(
        self,
        file_path: str | Path,
        extract_pii: bool = False,
    ) -> ParseResult:
        """
        전체 파싱 파이프라인 실행

        Args:
            file_path: PDF 파일 경로
            extract_pii: True면 PII 포함, False면 마스킹

        Returns:
            ParseResult: 추출된 필드와 메타데이터
        """
        start_time = time.time()
        model_used = None

        try:
            # 1단계: PDF 파싱 (CPU 작업이므로 스레드에서 실행)
            parsed_doc = await asyncio.to_thread(self.pdf_parser.parse, file_path)

            # 2단계: 이미지 PDF인 경우 VLM OCR + PII 처리
            if not parsed_doc.is_text_pdf:
                logger.info("이미지 기반 PDF 감지 → VLM OCR 파이프라인 실행")
                image_processor = self._get_image_processor()
                pdf_bytes = Path(file_path).read_bytes()
                parsed_doc, _masking_result = await image_processor.process(pdf_bytes, extract_pii=extract_pii)
                masked_text = parsed_doc.full_text
            else:
                # 3단계: PII 마스킹 (개인정보 보호 - CPU 작업이므로 스레드에서 실행)
                if not extract_pii:
                    masking_result = await asyncio.to_thread(self.pii_masker.mask_text, parsed_doc.full_text)
                    parsed_doc.full_text = masking_result.masked_text
                masked_text = parsed_doc.full_text

            # 4단계: LLM을 통한 필드 추출
            extracted_fields, raw_response = await self.field_extractor.extract(
                parsed_doc,
                include_layout=True,
            )
            model_used = "gemini-2.5-flash-lite"

            # 신뢰도 점수 계산
            confidence_score = self._calculate_confidence(extracted_fields)
            processing_time = int((time.time() - start_time) * 1000)

            return ParseResult(
                success=True,
                extracted_fields=extracted_fields,
                raw_text=masked_text,
                confidence_score=confidence_score,
                error_message=None,
                processing_time_ms=processing_time,
                model_used=model_used,
                needs_ocr=False,
            )

        except Exception as e:
            processing_time = int((time.time() - start_time) * 1000)
            return ParseResult(
                success=False,
                extracted_fields=None,
                raw_text=None,
                confidence_score=None,
                error_message=str(e),
                processing_time_ms=processing_time,
                model_used=model_used,
                needs_ocr=False,
            )

    async def parse_bytes(
        self,
        pdf_bytes: bytes,
        extract_pii: bool = False,
    ) -> ParseResult:
        """
        바이트 데이터로 PDF 파싱
        """
        with tracer.start_as_current_span("resume_parse_pipeline") as span:
            start_time = time.time()
            model_used = None
            span.set_attribute("extract_pii", extract_pii)

            try:
                # 1단계: 바이트에서 PDF 파싱 (텍스트 추출)
                with tracer.start_as_current_span("pdf_parse_bytes"):
                    parsed_doc = await asyncio.to_thread(self.pdf_parser.parse_bytes, pdf_bytes)
                
                logger.debug("1단계 PDF 파싱 완료 (텍스트 추출)")
                span.set_attribute("pdf.is_text_pdf", parsed_doc.is_text_pdf)
                span.set_attribute("pdf.total_pages", parsed_doc.total_pages)

                # 이미지 기반 PDF → VLM OCR + PII 처리
                if not parsed_doc.is_text_pdf:
                    logger.info("이미지 기반 PDF 감지 → VLM OCR 파이프라인 실행")
                    with tracer.start_as_current_span("vlm_ocr_pipeline"):
                        image_processor = self._get_image_processor()
                        parsed_doc, ocr_masking_result = await image_processor.process(pdf_bytes, extract_pii=extract_pii)
                    masked_text = parsed_doc.full_text
                else:
                    # 2단계: Presidio PII 마스킹
                    if not extract_pii:
                        with tracer.start_as_current_span("pii_masking"):
                            masking_result = await asyncio.to_thread(self.pii_masker.mask_text, parsed_doc.full_text)
                            masked_text = masking_result.masked_text
                            span.set_attribute("pii.entities_count", len(masking_result.entities))
                    else:
                        masked_text = parsed_doc.full_text

                # 3단계: LLM을 통한 필드 추출
                with tracer.start_as_current_span("llm_field_extraction"):
                    from services.doc_ai.pdf_parser import ParsedDocument
                    masked_doc = ParsedDocument(
                        pages=parsed_doc.pages,
                        total_pages=parsed_doc.total_pages,
                        full_text=masked_text,
                        text_blocks=parsed_doc.text_blocks,
                        is_text_pdf=parsed_doc.is_text_pdf,
                    )
                    extracted_fields, raw_response = await self.field_extractor.extract(
                        masked_doc,
                        include_layout=True,
                    )
                model_used = "gemini-2.5-flash-lite"
                span.set_attribute("llm.model", model_used)

                # 4단계: 신뢰도 계산
                confidence_score = self._calculate_confidence(extracted_fields)
                processing_time = int((time.time() - start_time) * 1000)
                span.set_attribute("processing_time_ms", processing_time)

                return ParseResult(
                    success=True,
                    extracted_fields=extracted_fields,
                    raw_text=masked_text,
                    confidence_score=confidence_score,
                    error_message=None,
                    processing_time_ms=processing_time,
                    model_used=model_used,
                    needs_ocr=False,
                )

            except Exception as e:
                logger.error(f"파이프라인 실행 실패: {e}")
                span.record_exception(e)
                processing_time = int((time.time() - start_time) * 1000)
                return ParseResult(
                    success=False,
                    extracted_fields=None,
                    raw_text=None,
                    confidence_score=None,
                    error_message=str(e),
                    processing_time_ms=processing_time,
                    model_used=model_used,
                    needs_ocr=False,
                )

    def _mask_pii(self, fields: ExtractedFields) -> ExtractedFields:
        """
        개인 식별 정보 마스킹

        참고: PII는 이미 Presidio를 통해 텍스트 레벨에서 마스킹됨.
        이 함수는 추가적인 필드 레벨 마스킹이 필요할 때 사용.
        """
        # personal_info가 제거되어 현재는 추가 마스킹 불필요
        return fields.model_copy(deep=True)

    def _calculate_confidence(self, fields: ExtractedFields) -> float:
        """
        추출 신뢰도 점수 계산 (0-1)

        추출된 필드의 완성도를 기반으로 계산합니다.
        """
        scores = []

        # 제목 완성도 (15%)
        title_score = 1.0 if fields.title else 0.0
        scores.append(title_score * 0.15)

        # 학력 완성도 (20%)
        if fields.education:
            edu_score = min(len(fields.education) / 2, 1.0)
            scores.append(edu_score * 0.2)
        else:
            scores.append(0)

        # 경력 완성도 (35%)
        if fields.work_experience:
            exp_score = min(len(fields.work_experience) / 3, 1.0)
            scores.append(exp_score * 0.35)
        else:
            scores.append(0)

        # 프로젝트 완성도 (15%)
        if fields.projects:
            proj_score = min(len(fields.projects) / 2, 1.0)
            scores.append(proj_score * 0.15)
        else:
            scores.append(0)

        # 자격증/수상/기타 보너스 (15%)
        bonus = 0
        if fields.certifications:
            bonus += 0.05
        if fields.awards:
            bonus += 0.05
        if fields.etc:
            bonus += 0.05
        scores.append(bonus)

        return round(sum(scores), 2)
