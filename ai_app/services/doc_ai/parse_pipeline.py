"""파싱 파이프라인 - 이력서 파싱 워크플로우 조율"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field
from schemas.resumes import Project, WorkExperience

from services.doc_ai.field_extractor import FieldExtractor
from services.doc_ai.pdf_parser import PDFParser
from services.doc_ai.pii_masker import PIIMasker, get_pii_masker

# 로거 설정
logger = logging.getLogger(__name__)


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
            # 1단계: PDF 파싱
            parsed_doc = self.pdf_parser.parse(file_path)

            # 2단계: OCR 필요 여부 확인
            if not parsed_doc.is_text_pdf:
                processing_time = int((time.time() - start_time) * 1000)
                return ParseResult(
                    success=False,
                    extracted_fields=None,
                    raw_text=None,
                    confidence_score=None,
                    error_message="이미지 기반 PDF입니다. OCR 처리가 필요합니다.",
                    processing_time_ms=processing_time,
                    model_used=None,
                    needs_ocr=True,
                )

            # 3단계: LLM을 통한 필드 추출
            extracted_fields, raw_response = await self.field_extractor.extract(
                parsed_doc,
                include_layout=True,
            )
            model_used = "gemini-2.0-flash"

            # 4단계: PII 마스킹 (extract_pii가 False인 경우)
            if not extract_pii:
                extracted_fields = self._mask_pii(extracted_fields)

            # 신뢰도 점수 계산
            confidence_score = self._calculate_confidence(extracted_fields)
            processing_time = int((time.time() - start_time) * 1000)

            return ParseResult(
                success=True,
                extracted_fields=extracted_fields,
                raw_text=parsed_doc.full_text,
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

        Args:
            pdf_bytes: PDF 바이트 데이터
            extract_pii: True면 PII 포함, False면 마스킹

        Returns:
            ParseResult: 추출된 필드와 메타데이터
        """
        start_time = time.time()
        model_used = None

        try:
            # 1단계: 바이트에서 PDF 파싱 (텍스트 추출)
            parsed_doc = self.pdf_parser.parse_bytes(pdf_bytes)
            logger.info("=" * 60)
            logger.info("1단계 PDF 파싱 완료 (텍스트 추출)")
            logger.info(f"  - 페이지 수: {parsed_doc.total_pages}")
            logger.info(f"  - 텍스트 기반 PDF: {parsed_doc.is_text_pdf}")
            logger.info(f"  - 추출된 텍스트 길이: {len(parsed_doc.full_text)} 글자")
            text_preview = parsed_doc.full_text[:200] if len(parsed_doc.full_text) > 200 else parsed_doc.full_text
            logger.info(f"  - 텍스트 미리보기: {text_preview}...")

            # OCR 필요 여부 확인
            if not parsed_doc.is_text_pdf:
                logger.warning("  - OCR 필요: 이미지 기반 PDF입니다.")
                processing_time = int((time.time() - start_time) * 1000)
                return ParseResult(
                    success=False,
                    extracted_fields=None,
                    raw_text=None,
                    confidence_score=None,
                    error_message="이미지 기반 PDF입니다. OCR 처리가 필요합니다.",
                    processing_time_ms=processing_time,
                    model_used=None,
                    needs_ocr=True,
                )

            # 2단계: Presidio PII 마스킹 (LLM 호출 전)
            logger.info("-" * 60)
            logger.info("2단계 Presidio PII 마스킹")
            if not extract_pii:
                masking_result = self.pii_masker.mask_text(parsed_doc.full_text)
                masked_text = masking_result.masked_text
                logger.info(f"  - 발견된 PII 개수: {len(masking_result.entities)}개")
                for entity in masking_result.entities:
                    logger.info(f"    • {entity.entity_type}: {entity.masked_text}")
                masked_preview = masked_text[:200] if len(masked_text) > 200 else masked_text
                logger.info(f"  - 마스킹된 텍스트 미리보기: {masked_preview}...")
            else:
                masked_text = parsed_doc.full_text
                logger.info("  - PII 마스킹 스킵 (extract_pii=True)")

            # 3단계: LLM을 통한 필드 추출 (마스킹된 텍스트 사용)
            logger.info("-" * 60)
            logger.info("3단계 LLM 필드 추출 시작...")

            # 마스킹된 텍스트로 임시 ParsedDocument 생성
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
            model_used = "gemini-2.0-flash"
            logger.info("3단계 LLM 필드 추출 완료")
            logger.info(f"  - 사용 모델: {model_used}")
            logger.info(f"  - 제목: {extracted_fields.title}")
            logger.info(f"  - 학력 수: {len(extracted_fields.education)}개")
            logger.info(f"  - 경력 수: {len(extracted_fields.work_experience)}개")
            logger.info(f"  - 프로젝트 수: {len(extracted_fields.projects)}개")
            logger.info(f"  - 자격증 수: {len(extracted_fields.certifications)}개")
            logger.info(f"  - 수상 내역 수: {len(extracted_fields.awards)}개")

            # 4단계: 스키마 정규화 및 신뢰도 계산
            logger.info("-" * 60)
            confidence_score = self._calculate_confidence(extracted_fields)
            processing_time = int((time.time() - start_time) * 1000)
            logger.info("4단계 스키마 정규화 완료")
            logger.info(f"  - 신뢰도 점수: {confidence_score}")
            logger.info(f"  - 총 처리 시간: {processing_time}ms")
            logger.info("=" * 60)

            return ParseResult(
                success=True,
                extracted_fields=extracted_fields,
                raw_text=masked_text,  # 마스킹된 텍스트 반환
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
