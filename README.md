# 19-team-project-ai

(설계 기준 계획 - *바뀔 수 있음)

<pre><code>ai_app/
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
</code></pre>
