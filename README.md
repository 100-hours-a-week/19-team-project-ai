# Re-fit AI

현직자 피드백과 AI 분석을 결합해, 구직자에게 맞춤형 취업 준비 지원을 제공하는 AI 서비스입니다.  
이력서 PDF를 구조화 데이터로 변환하고, 채용공고와 비교한 리포트를 생성하며,  
현직자 추천과 AI 멘토형 대화 기능까지 하나의 흐름으로 연결했습니다.

---

## 프로젝트 소개

취업 준비 과정에서는  
- 현재 내 이력서가 어떤 수준인지 파악하기 어렵고,
- 어떤 현직자에게 조언을 받아야 할지 모르며,
- 채용공고와 내 경험의 차이를 스스로 분석하는 데 시간이 많이 듭니다.

Re-fit AI는 이러한 문제를 줄이기 위해  
**이력서 파싱(DocAI) → 채용공고 분석 리포트(Repo) → 현직자 추천(Reco) → AI 멘토 대화(Agent/AIMento)**  
흐름으로 취업 준비를 돕는 AI 서비스를 구현한 프로젝트입니다.

---

## 핵심 기능

### 1) DocAI - 이력서 PDF 구조화
- PDF 업로드 후 텍스트 추출 및 OCR 처리
- 개인정보 마스킹(PII masking)
- LLM 기반 이력서 필드 추출 및 정규화
- 이력서 여부 분류 로직 포함

### 2) Repo - 채용공고 분석 리포트
- 채용공고 링크/텍스트 파싱
- 이력서와 공고를 비교해 적합도 및 커버리지 산출
- 부족한 역량, 강점, 액션플랜 등 리포트 생성

### 3) Reco - 현직자 추천
- 임베딩 기반 유사도 검색
- 벡터 검색을 통한 현직자 후보 추천
- 필요 시 리랭킹 구조 확장 가능

### 4) Agent / AIMento - 대화형 지원
- 사용자 의도 분기
- 조건 수집(slot filling)
- 질문 정제(question refine)
- RAG 기반 멘토형 응답 확장 구조

---

## 시스템 아키텍처

이 프로젝트는 **FastAPI 기반 AI 서비스**로 구성되어 있으며,  
도메인별 기능을 `doc_ai`, `repo`, `reco`, `agent` 서비스로 분리해 설계했습니다.  
또한 `jobs` 레이어를 통해 비동기 처리 확장 가능성을 고려했고,  
`adapters` 레이어에서 LLM, OCR, 벡터DB, Redis, S3 같은 외부 의존성을 분리했습니다.

### 구조 요약
- **API Layer**: 엔드포인트 및 라우팅
- **Controller Layer**: 요청 흐름 조율
- **Service Layer**: 도메인별 핵심 파이프라인
- **Jobs Layer**: 비동기 상태 관리 및 디스패치
- **Adapters Layer**: 외부 AI/Storage/DB 연동 추상화

---

## 기술 스택

### Backend
- Python
- FastAPI
- Pydantic

### AI / Data
- LLM
- OCR
- Vector Search / Embedding
- RAG

### Infra / External
- Redis
- S3
- VectorDB
- Docker

---

## 프로젝트 구조

```
ai_app/
├── main.py                         # FastAPI Entrypoint
├── api/
│   ├── main.py                     # router include, middleware(Tracing/RateLimit)
│   └── endpoints/
│       ├── health_router.py        # GET /health
│       ├── jobs_router.py          # GET /jobs/{job_id}
│       ├── resumes_router.py       # POST /resumes, POST /resumes/{id}/parse, GET /resumes/{id}
│       ├── resume_clf_router.py    # POST /resumes/resume-classifier (내부 검증)
│       ├── reco_router.py          # POST /mentors/recommend
│       ├── repo_router.py          # POST /repo/job, POST /repo/generate
│       ├── agent_router.py         # POST/GET /agent/sessions, POST /agent/reply
│       └── aimento_router.py       # POST/GET /aimento/sessions
│
├── controllers/                    # HTTP 레이어 조율자
│   ├── jobs_controller.py
│   ├── resumes_controller.py
│   ├── reco_controller.py
│   ├── repo_controller.py
│   ├── agent_controller.py
│   └── aimento_controller.py
│
├── schemas/                        # Pydantic 계약(스펙의 Single Source of Truth)
│   ├── common.py                   # request_id, error, meta(model/prompt/corpus_version)
│   ├── jobs.py
│   ├── resumes.py
│   ├── reco.py
│   ├── repo.py
│   ├── agent.py
│   └── aimento.py
│
├── services/                       # 도메인별 파이프라인(업무 흐름)
│   ├── doc_ai/
│   │   ├── upload.py               # /resumes
│   │   ├── parse_pipeline.py       # /resumes/{id}/parse (오케스트레이션)
│   │   ├── pdf_parser.py           # 텍스트 PDF 파싱
│   │   ├── ocr_pipeline.py         # OCR 경로
│   │   ├── pii_masking.py          # Presidio(텍스트), VLM(시각) 마스킹 연결
│   │   ├── resume_classifier.py    # 자체 이력서 판별(Text Classifier)
│   │   └── field_extractor.py      # LLM 필드 추출/정규화
│   │
│   ├── repo/
│   │   ├── job_parser.py           # /repo/job (링크/텍스트 추출)
│   │   ├── report_pipeline.py      # /repo/generate (리포트 생성 오케스트레이션)
│   │   ├── scoring.py              # 커버리지/적합도 계산
│   │   └── summarizer.py           # 요약/액션플랜 생성
│   │
│   ├── reco/
│   │   ├── embedder.py             # 임베딩 생성
│   │   ├── retrieval.py            # VectorDB 검색
│   │   └── reranker.py             # (옵션) 재순위화
│   │
│   └── agent/
│       ├── session.py              # /agent/sessions, /aimento/sessions 상태 관리(주로 Redis)
│       ├── intent_router.py        # /agent/reply: RECO vs AIMENTO 의도 분기
│       ├── slot_filling.py         # 조건 수집
│       ├── question_refine.py      # 질문 코칭
│       └── aimento_chat.py         # AIMento: RAG + Generation(스트리밍 확장)
│
├── jobs/                           # Job 상태/디스패치(비동기 운영의 중심)
│   ├── job_store.py                # DB/Redis에 상태 저장(QUEUED/RUNNING/...)
│   └── dispatcher.py               # Sync/Async 분기(큐 발행 or 즉시 실행)
│
└── adapters/                       # 외부 의존성(Provider) 래퍼
    ├── llm_client.py               # Gemini 등
    ├── ocr_client.py
    ├── vlm_mask_client.py
    ├── storage_client.py           # S3 wrapper
    ├── vectordb_client.py
    └── cache_client.py             # Redis wrapper
```

## 실행방법
```
# 1. 저장소 클론
git clone https://github.com/100-hours-a-week/19-team-project-ai.git

# 2. 환경변수 설정
cp .env.example .env

# 3. 의존성 설치
# 프로젝트 환경에 맞는 패키지 매니저 사용

# 4. 서버 실행
docker-compose up --build
```

