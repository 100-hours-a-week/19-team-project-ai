import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import lru_cache

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

logger = logging.getLogger(__name__)


@dataclass
class PIIEntity:
    """마스킹된 PII 엔티티 정보"""

    entity_type: str
    start: int
    end: int
    original_text: str
    masked_text: str
    score: float = 1.0  # 신뢰도 점수 추가


@dataclass
class MaskingResult:
    """마스킹 결과"""

    masked_text: str
    entities: list[PIIEntity] = field(default_factory=list)
    processing_time: float = 0.0
    method_name: str = ""


class PIIMasker(ABC):
    """PII 마스커 추상 기본 클래스"""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def mask_text(self, text: str) -> MaskingResult:
        pass


class PresidioPIIMasker(PIIMasker):
    """Presidio + 정규식 기반 PII 마스킹 서비스"""

    def __init__(self):
        # Analyzer 초기화 (영어 기본)
        self.analyzer = AnalyzerEngine()
        self.anonymizer = AnonymizerEngine()

        # 한국어 패턴 정규식 (Presidio 외부에서 직접 처리)
        self.korean_patterns = {
            "PHONE_NUMBER": re.compile(r"(01[016789][-.\s]?\d{3,4}[-.\s]?\d{4})|(\d{2,3}[-.\s]?\d{3,4}[-.\s]?\d{4})"),
            "KR_RRN": re.compile(r"\d{6}[-\s]?[1-4]\d{6}"),
            "EMAIL": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
        }

        self.mask_replacements = {
            "PHONE_NUMBER": "[전화번호]",
            "KR_RRN": "[주민번호]",
            "EMAIL": "[이메일]",
            "EMAIL_ADDRESS": "[이메일]",
            "PERSON": "[이름]",
        }

    @property
    def name(self) -> str:
        return "Presidio (Regex + Logic)"

    def mask_text(self, text: str) -> MaskingResult:
        if not text or not text.strip():
            return MaskingResult(masked_text=text, entities=[])

        start_time = time.time()
        entities = []
        masked_text = text

        try:
            # 1. 한국어 패턴 먼저 처리 (정규식)
            for entity_type, pattern in self.korean_patterns.items():
                matches = list(pattern.finditer(masked_text))
                for match in reversed(matches):  # 뒤에서부터 처리 (인덱스 변경 방지)
                    replacement = self.mask_replacements.get(entity_type, "[MASKED]")
                    original = match.group()
                    entities.append(
                        PIIEntity(
                            entity_type=entity_type,
                            start=match.start(),
                            end=match.end(),
                            original_text=original,
                            masked_text=replacement,
                        )
                    )
                    masked_text = masked_text[: match.start()] + replacement + masked_text[match.end() :]

            # 2. Presidio로 영어 PII 추가 감지
            try:
                results = self.analyzer.analyze(
                    text=masked_text,
                    language="en",
                    entities=["EMAIL_ADDRESS"],  # PERSON 제거
                    score_threshold=0.7,  # 높은 threshold로 오탐 감소
                )

                if results:
                    anonymized = self.anonymizer.anonymize(
                        text=masked_text,
                        analyzer_results=results,
                        operators={
                            "DEFAULT": OperatorConfig("replace", {"new_value": "[MASKED]"}),
                            "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "[이메일]"}),
                        },
                    )
                    masked_text = anonymized.text

                    for item in anonymized.items:
                        entities.append(
                            PIIEntity(
                                entity_type=item.entity_type,
                                start=item.start,
                                end=item.end,
                                original_text=item.text,
                                masked_text=self.mask_replacements.get(item.entity_type, "[MASKED]"),
                            )
                        )
            except Exception as presidio_error:
                logger.warning(f"Presidio 분석 스킵: {presidio_error}")

            processing_time = time.time() - start_time
            logger.info(f"PII 마스킹 완료 ({self.name}): {len(entities)}개 엔티티 발견")

            return MaskingResult(
                masked_text=masked_text, entities=entities, processing_time=processing_time, method_name=self.name
            )

        except Exception as e:
            logger.error(f"PII 마스킹 실패: {e}")
            return MaskingResult(masked_text=text, entities=[])


class KcBERTPIIMasker(PIIMasker):
    """KcBERT 기반 한국어 PII 마스킹 (seungkukim/korean-pii-masking)"""

    def __init__(self):
        self.pipeline = None
        self.available = False

        try:
            import os

            # Meta tensor 비활성화 (transformers 4.39+ 호환)
            os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"

            from transformers import pipeline

            # seungkukim/korean-pii-masking 모델 로드
            model_name = "seungkukim/korean-pii-masking"

            # 직접 pipeline으로 로드 (가장 단순한 방법)
            self.pipeline = pipeline(
                "token-classification",
                model=model_name,
                tokenizer=model_name,
                aggregation_strategy="simple",
                device="cpu",
            )
            self.available = True
            print("✅ KcBERT 기반 PII 모델 로드 완료 (CPU)")

        except Exception as e:
            print(f"⚠️  KcBERT 모델 로드 실패: {e}")
            print("   설치: pip install transformers torch")

    @property
    def name(self) -> str:
        return "KcBERT (seungkukim/korean-pii-masking)"

    def mask_text(self, text: str) -> MaskingResult:
        if not self.available:
            return MaskingResult(
                masked_text=text, entities=[], processing_time=0, method_name=f"{self.name} (사용 불가)"
            )

        start_time = time.time()

        # 텍스트가 너무 길면 잘라서 처리해야 할 수도 있지만, 일단은 그냥 넣습니다.
        # Transformers pipeline은 길이가 길면 자동으로 잘릴 수 있으니 주의.
        try:
            results = self.pipeline(text)
        except Exception as e:
            logger.error(f"KcBERT 추론 실패: {e}")
            return MaskingResult(masked_text=text, entities=[])

        detected_entities = []
        masked_text = text

        # 역순으로 처리하여 인덱스 유지
        # results는 dict list 형태
        for entity in sorted(results, key=lambda x: x["start"], reverse=True):
            entity_type = entity["entity_group"]

            # 엔티티 타입 매핑
            type_mapping = {
                "PS_NAME": "NAME",
                "QT_MOBILE": "PHONE",
                "QT_PHONE": "PHONE",
                "TMI_EMAIL": "EMAIL",
                "QT_RESIDENT_NUMBER": "RRN",
                "QT_CARD_NUMBER": "CARD",
            }

            # 마스킹 라벨 생성
            mapped_type = type_mapping.get(entity_type, entity_type)
            korean_labels = {
                "NAME": "이름",
                "PHONE": "전화번호",
                "EMAIL": "이메일",
                "RRN": "주민번호",
                "CARD": "카드번호",
            }
            label_text = korean_labels.get(mapped_type, mapped_type)
            masked_label = f"[{label_text}]"

            detected_entities.append(
                PIIEntity(
                    entity_type=mapped_type,
                    original_text=entity["word"],
                    start=entity["start"],
                    end=entity["end"],
                    masked_text=masked_label,
                    score=entity["score"],
                )
            )

            masked_text = masked_text[: entity["start"]] + masked_label + masked_text[entity["end"] :]

        processing_time = time.time() - start_time

        return MaskingResult(
            masked_text=masked_text, entities=detected_entities, processing_time=processing_time, method_name=self.name
        )


@lru_cache(maxsize=1)
def get_pii_masker() -> PIIMasker:
    """PIIMasker 싱글톤 (thread-safe via lru_cache)

    기본값: KcBERT, 사용 불가 시 Presidio로 fallback
    """
    masker = KcBERTPIIMasker()
    if not getattr(masker, "available", False):
        logger.warning("KcBERT 사용 불가, Presidio로 대체합니다.")
        return PresidioPIIMasker()
    return masker
