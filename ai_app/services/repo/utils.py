"""채용공고 관련 유틸리티 함수"""



# 표준 직무 리스트
STANDARD_POSITIONS = [
    "벡엔드 개발자",
    "프론트엔드 개발자",
    "풀스택 개발자",
    "모바일 앱 개발자",
    "데이터 엔지니어",
    "데이터 분석가",
    "머신러닝 엔지니어",
    "클라우드 엔지니어",
    "DevOps 엔지니어",
    "플랫폼 엔지니어",
    "SRE",
    "보안 엔지니어",
    "QA 엔지니어",
    "테크니컬 PM",
    "솔루션 아키텍트",
    "AI 엔지니어",
    "LLM 엔지니어",
    "머신러닝 리서처",
    "딥러닝 엔지니어",
    "데이터 사이언티스트",
    "MLOps 엔지니어",
    "AI 플랫폼 엔지니어",
    "AI 서비스 엔지니어",
    "컴퓨터 비전 엔지니어",
    "자연어 처리(NLP) 엔지니어",
]


def map_standard_position(title: str) -> str:
    """채용공고 제목을 기반으로 표준 직무 명칭으로 맵핑"""
    if not title:
        return "기타()"

    # 1. 표준 리스트와 정확히 일치하거나 포함되어 있는지 확인
    # 대소문자 구분 없이 매칭하기 위해 소문자 변환 후 체크 (한글 포함이므로 주의)
    # 한글의 경우 공백 제거 후 비교하는 정규화 시도
    normalized_title = title.replace(" ", "").lower()

    for position in STANDARD_POSITIONS:
        normalized_pos = position.replace(" ", "").lower()

        # 정규표현식으로 경계 확인하며 포함 여부 체크
        # 예: "프론트엔드"가 "프론트엔드 개발자"에 포함되거나 그 반대인 경우
        if normalized_pos in normalized_title or normalized_title in normalized_pos:
            return position

    # 2. 매칭되는 항목이 없으면 기타([원문]) 반환
    return f"기타({title})"
