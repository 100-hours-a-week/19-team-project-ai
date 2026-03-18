"""개인정보(PII) 마스킹 모듈 — 정규식 기반 1차 마스킹"""

import re

# 전화번호 (010-1234-5678, 01012345678, 010 1234 5678)
_PHONE_PATTERN = re.compile(r"01[016789][-\s]?\d{3,4}[-\s]?\d{4}")

# 이메일
_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# 주민등록번호 (000000-0000000)
_SSN_PATTERN = re.compile(r"\d{6}[-\s]?[1-4]\d{6}")

# 카드번호 (0000-0000-0000-0000)
_CARD_PATTERN = re.compile(r"\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}")

# 계좌번호 (은행명 + 숫자열)
_ACCOUNT_PATTERN = re.compile(r"(?:계좌|입금)\s*[:\s]?\s*\d{2,6}[-\s]?\d{2,8}[-\s]?\d{2,8}")


def mask_pii_regex(text: str) -> str:
    """정규식 기반 PII 마스킹 (확실한 패턴만 처리)"""
    text = _SSN_PATTERN.sub("[주민번호]", text)
    text = _PHONE_PATTERN.sub("[연락처]", text)
    text = _EMAIL_PATTERN.sub("[이메일]", text)
    text = _CARD_PATTERN.sub("[카드번호]", text)
    text = _ACCOUNT_PATTERN.sub("[계좌정보]", text)
    return text
