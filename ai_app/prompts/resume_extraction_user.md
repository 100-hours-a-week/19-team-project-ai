Extract all relevant information from the following resume text and return it as a structured JSON.

Resume Text:
---
{resume_text}
---

## IMPORTANT RULES:

### 제목 (title)
이력서 제목을 텍스트로만 15자 이내로 요약해서 표기

### 직무 (job)
다음 중 하나로만 분류하세요. 해당 없으면 null:
- 소프트웨어 엔지니어
- 서버 개발자
- 웹 개발자
- 프론트엔드 개발자
- 자바 개발자
- 머신러닝 엔지니어
- 파이썬 개발자
- DevOps/시스템 관리자

### 직책 (position)
다음과 유사한 형태로 분류하세요. 해당 없으면 null:
- 팀장
- 시니어 엔지니어
- 주니어 엔지니어
- CPO
- CTO
- COO
- CEO
- VP
- 본부장
- 실장
- 센터장
- 파트장
- 개발 리더
- 프로덕트 리더
- 인턴


### 프로젝트 (projects)
- 경력의 업무 내용/성과가 명시되어 있으면 프로젝트에도 추가
- 경력 기간(예: 2024.07 ~ 2025.12) 내에 포함된 프로젝트들을 각각 리스트로 분리
- 프로젝트명, 기간, 설명만 포함 (역할/성과는 설명에 포함)

### 학력 (education)
- 가장 최근 학력만 포함
- 형식: "OO대학교 졸업" 또는 "OO대학원 졸업"

### 자격증 (certifications)
- 텍스트로만 표기 (예: "정보처리기사 (2023)")

Return the extracted information as JSON object (without markdown code blocks) with this structure:

{{
    "title" : "이력서 제목",
    "work_experience": [
        {{
            "company": "회사명",
            "position": "직책 or null",
            "job": "직무 or null",
            "start_date": "YYYY-MM or YYYY or null",
            "end_date": "YYYY-MM or YYYY or 'Present' or null",
            "description": "업무 설명"
        }}
    ],
    "projects": [
        {{
            "name": "프로젝트명",
            "start_date": "YYYY-MM or YYYY or null",
            "end_date": "YYYY-MM or YYYY or null",
            "description": "프로젝트 설명 (역할, 성과 포함)"
        }}
    ],
    "education": ["OO대학교 졸업"],
    "awards": ["수상 내역 텍스트"],
    "certifications": ["자격증명 (YYYY)"],
    "etc": ["대외 활동/기타 설명"]
}}

Extract and return only the JSON:
