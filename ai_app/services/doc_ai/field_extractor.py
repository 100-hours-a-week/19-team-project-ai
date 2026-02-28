"""필드 추출기 - LLM 기반 이력서 필드 추출 및 정규화"""

from typing import Any

from adapters.llm_client import LLMClient, get_llm_client
from opentelemetry import trace
from prompts import get_resume_extraction_prompts

from services.doc_ai.pdf_parser import ParsedDocument


tracer = trace.get_tracer(__name__)


class FieldExtractor:
    """LLM을 사용한 이력서 구조화 필드 추출"""

    def __init__(self, llm_client: LLMClient | None = None):
        self._llm_client = llm_client

    @property
    def llm_client(self) -> LLMClient:
        """LLM 클라이언트 지연 초기화"""
        if self._llm_client is None:
            self._llm_client = get_llm_client()
        return self._llm_client

    async def extract(
        self,
        parsed_doc: ParsedDocument,
        include_layout: bool = True,
    ) -> tuple[Any, dict[str, Any]]:
        """
        파싱된 문서에서 구조화된 필드 추출

        Args:
            parsed_doc: 파싱된 PDF 문서
            include_layout: 레이아웃 정보 포함 여부

        Returns:
            (ExtractedFields, 원본 응답 dict) 튜플
        """
        # 순환 임포트 방지를 위해 여기서 임포트
        from services.doc_ai.parse_pipeline import ExtractedFields

        # LLM용 텍스트 준비
        if include_layout:
            resume_text = self._prepare_text_with_layout(parsed_doc)
        else:
            resume_text = parsed_doc.full_text

        # 외부 파일에서 프롬프트 로드
        system_prompt, user_prompt_template = get_resume_extraction_prompts()
        user_prompt = user_prompt_template.format(resume_text=resume_text)

        # LLM 호출하여 추출
        import logging

        logger = logging.getLogger(__name__)

        try:
            with tracer.start_as_current_span("llm_generate_json"):
                raw_response = await self.llm_client.generate_json(
                    prompt=user_prompt,
                    system_instruction=system_prompt,
                    temperature=0.1,
                )
            logger.debug(f"LLM 응답 타입: {type(raw_response)}")
            logger.debug(f"LLM 응답 키: {raw_response.keys() if isinstance(raw_response, dict) else 'N/A'}")
        except Exception as e:
            logger.error(f"LLM 호출 에러: {e}")
            raise

        # 응답 파싱 및 검증
        extracted = self._parse_response(raw_response, ExtractedFields)

        return extracted, raw_response

    def _prepare_text_with_layout(self, parsed_doc: ParsedDocument) -> str:
        """레이아웃 힌트를 포함한 텍스트 준비"""
        parts = []

        for page in parsed_doc.pages:
            if parsed_doc.total_pages > 1:
                parts.append(f"\n[페이지 {page.page_num + 1}]\n")

            # 위치 기준으로 블록 정렬
            sorted_blocks = sorted(
                page.text_blocks,
                key=lambda b: (b.y0, b.x0),
            )

            current_y = 0
            for block in sorted_blocks:
                # 큰 수직 간격이 있으면 섹션 구분 힌트 추가
                if block.y0 - current_y > 50:
                    parts.append("\n---\n")

                parts.append(block.text)
                current_y = block.y1

        return "\n".join(parts)

    def _parse_response(self, raw_response: dict[str, Any], extracted_fields_cls: type) -> Any:
        """LLM 응답을 ExtractedFields로 파싱 및 검증"""
        try:
            return extracted_fields_cls.model_validate(raw_response)
        except Exception:
            # 검증 실패 시 부분 추출 시도
            return extracted_fields_cls(
                title=raw_response.get("title"),
                work_experience=self._safe_get_list(raw_response, "work_experience"),
                projects=self._safe_get_list(raw_response, "projects"),
                education=self._safe_get_list(raw_response, "education"),
                awards=raw_response.get("awards", []),
                certifications=self._safe_get_list(raw_response, "certifications"),
                etc=self._safe_get_list(raw_response, "etc"),
            )

    def _safe_get(self, data: dict, key: str, default: Any) -> Any:
        """기본값과 함께 안전하게 값 가져오기"""
        value = data.get(key)
        return value if value is not None else default

    def _safe_get_list(self, data: dict, key: str) -> list:
        """안전하게 리스트 값 가져오기"""
        value = data.get(key)
        if isinstance(value, list):
            return value
        return []


async def extract_resume_fields(
    parsed_doc: ParsedDocument,
    llm_client: LLMClient | None = None,
) -> tuple[Any, dict[str, Any]]:
    """
    파싱된 문서에서 필드 추출 편의 함수

    Args:
        parsed_doc: 파싱된 PDF 문서
        llm_client: LLM 클라이언트 (미제공 시 기본값 사용)

    Returns:
        (ExtractedFields, 원본 응답 dict) 튜플
    """
    extractor = FieldExtractor(llm_client)
    return await extractor.extract(parsed_doc)
