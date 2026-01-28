# Re-Fit AI Service

AI 기반 멘토-멘티 매칭 및 추천 서비스

---

## 📁 프로젝트 구조

```
19-team-project-ai/
├── ai_app/              # FastAPI 애플리케이션
│   ├── api/            # API 엔드포인트
│   ├── controllers/    # 비즈니스 로직
│   ├── services/       # 서비스 레이어
│   └── adapters/       # 외부 연동
├── .github/
│   └── workflows/
│       ├── ci.yml      # CI 파이프라인
│       ├── cd.yml      # CD 파이프라인
│       └── rollback.yml # 롤백 워크플로우
├── scripts/            # 유틸리티 스크립트
├── pyproject.toml      # Python 프로젝트 설정 (단일 소스)
└── requirements.txt    # 팀원 참조용 (자동 동기화)
```

---

## 🚀 배포 프로세스

### **CI/CD 파이프라인**

```
PR 생성
    ↓
[CI] Lint & Test (PR only)
    ↓
머지 to develop
    ↓
[CI] Integration Test
    ↓
[CI] Wheel 빌드 & S3 업로드
    ↓
[CD] 트리거 (자동)
    ↓
[CD] 배포 to EC2
    ↓
헬스체크 & Discord 알림
```

### **배포 단계 (CD)**

1. **백업 생성**
   - 코드 백업: `/backups/ai/code_YYYYMMDDHHMMSS/`
   - Wheel 백업: `/backups/ai/wheel_YYYYMMDDHHMMSS/`

2. **Wheel 패키지 설치**
   - S3에서 다운로드
   - `pip install --force-reinstall --no-cache-dir`

3. **서비스 재시작**
   - PM2 프로세스 정리
   - PM2 재시작
   - Caddy 리로드

4. **헬스체크**
   - 최대 5회 재시도
   - 실패 시 자동 롤백

---

## 🔄 롤백 시스템

### **롤백 워크플로우 사용법**

#### **1️⃣ 백업 목록 조회**

```bash
# GitHub Actions → AI Service Rollback 워크플로우 선택
# Mode: list 선택
```

**출력 예시:**
```
📂 Available Code Backups (Latest 10):
  - code_20260128100000 (Jan 28 10:00)
  - code_20260127150000 (Jan 27 15:00)
  ...

📦 Available Wheel Backups (Latest 10):
  - wheel_20260128100000 (Jan 28 10:00)
  - wheel_20260127150000 (Jan 27 15:00)
  ...
```

#### **2️⃣ 특정 버전으로 롤백**

```bash
# GitHub Actions → AI Service Rollback 워크플로우 선택
# Mode: restore
# Backup ID: 20260127150000  (또는 code_20260127150000)
# Restore dependencies: true
```

#### **3️⃣ 최신 백업으로 긴급 롤백**

```bash
# Backup ID를 비워두면 자동으로 최신 백업 사용
# Mode: restore
# Backup ID: (비움)
# Restore dependencies: true
```

### **롤백 옵션**

| 옵션 | 설명 | 추천 |
|------|------|------|
| **Restore dependencies: true** | 코드 + Wheel 패키지 모두 복원 | ✅ 추천 (완전 복구) |
| **Restore dependencies: false** | 코드만 복원, 현재 venv 유지 | ⚠️ 의존성 호환 확인 필요 |

### **롤백 프로세스**

```
롤백 시작
    ↓
Safety Backup 생성 (현재 상태 임시 백업)
    ↓
PM2 프로세스 완전 정리
    ↓
코드 복원 (ai_app, pyproject.toml, requirements.txt)
    ↓
의존성 복원 (선택적, wheel 재설치)
    ↓
PM2 재시작
    ↓
헬스체크 (최대 10회, 점진적 대기)
    ↓
성공 → Safety backup 삭제
실패 → Safety backup으로 자동 복구 시도
```

### **다단계 복구 전략**

1. **Level 1**: 지정된 백업으로 롤백
2. **Level 2**: 헬스체크 실패 시, Safety backup으로 복구
3. **Level 3**: 모든 시도 실패 시, 수동 개입 필요 (상세 로그 제공)

---

## 🔧 의존성 관리

### **pyproject.toml (단일 소스)**

- **CI/CD에서 사용**: `python -m build --wheel`
- **의존성 추가**: `[project].dependencies`에 직접 추가
- **예시**:
  ```toml
  dependencies = [
      "fastapi>=0.109.0",
      "sentence-transformers>=2.2.0",
      ...
  ]
  ```

### **requirements.txt (팀원 참조용)**

- **로컬 개발**: `pip install -r ai_app/requirements.txt`
- **자동 동기화**: CI에서 pyproject.toml과 자동 동기화
- **수동 업데이트 금지**: pyproject.toml에서만 수정

### **의존성 동기화**

```bash
# requirements.txt를 수정한 경우, CI가 자동으로 pyproject.toml 동기화
# PR에 자동 커밋됨
```

### **로컬에서 pyproject.toml 업데이트**

```bash
# 현재 설치된 패키지를 pyproject.toml에 반영
python scripts/freeze-to-pyproject.py
```

---

## 🛠️ 개발 가이드

### **로컬 개발 환경 설정**

```bash
# 1. 가상환경 생성
python3 -m venv venv
source venv/bin/activate

# 2. 의존성 설치
pip install -r ai_app/requirements.txt

# 3. 개발 의존성 설치
pip install -e ".[dev]"

# 4. 서비스 실행
cd ai_app
uvicorn api.main:app --reload --port 8000
```

### **의존성 추가**

```bash
# 1. pyproject.toml에 추가
[project]
dependencies = [
    "new-package>=1.0.0",
    ...
]

# 2. 로컬 설치
pip install new-package

# 3. requirements.txt 업데이트 (선택)
pip freeze | grep new-package >> ai_app/requirements.txt

# 4. 커밋 & 푸시 (CI가 자동 동기화)
```

---

## 🏥 헬스체크

### **엔드포인트**

```bash
# 기본 헬스체크
curl http://localhost:8000/api/ai/health

# 응답 (성공)
{"status": "ok"}

# 응답 (실패)
{"detail": "Not Found"}  # 또는 500 에러
```

### **서비스 상태 확인**

```bash
# PM2 상태
pm2 status ai-service

# 로그 확인
pm2 logs ai-service --lines 50

# 에러 로그
tail -f /home/ubuntu/refit/logs/ai/error.log
```

---

## 🚨 트러블슈팅

### **배포 실패**

1. **pip install 타임아웃**
   - SSM 타임아웃: 30분 (1800초)
   - 큰 패키지 (torch, spacy) 설치 시간 고려

2. **의존성 충돌**
   - `grpcio` 버전 고정: 1.60~1.70
   - `pyproject.toml`에서 버전 범위 조정

3. **포트 충돌 (Errno 98)**
   - CD가 자동으로 포트 8000 정리
   - PM2 프로세스 완전 정리 로직 포함

### **롤백 실패**

1. **백업 없음**
   - 최소 1회 성공 배포 필요
   - Safety backup으로 임시 복구

2. **의존성 불일치**
   - `Restore dependencies: true` 사용
   - Wheel 패키지 함께 복원

3. **헬스체크 실패**
   - PM2 로그 확인: `pm2 logs ai-service`
   - 서버 에러 로그: `/home/ubuntu/refit/logs/ai/error.log`

---

## 📊 백업 관리

### **자동 백업**

- **배포 시**: 코드 + Wheel 자동 백업
- **보관 기간**: 7일 (자동 삭제)
- **위치**: `/home/ubuntu/refit/backups/ai/`

### **백업 구조**

```
/home/ubuntu/refit/backups/ai/
├── code_20260128100000/      # 코드 백업
│   └── ai_app/
├── wheel_20260128100000/     # Wheel 백업
│   └── refit_ai_service-0.1.0-py3-none-any.whl
└── safety_before_rollback_*/  # 임시 백업 (롤백 시)
```

---

## 🔐 환경 변수

### **GitHub Secrets**

| Secret | 설명 |
|--------|------|
| `AWS_ACCESS_KEY_ID` | AWS 인증 |
| `AWS_SECRET_ACCESS_KEY` | AWS 인증 |
| `EC2_INSTANCE_ID` | 배포 대상 EC2 |
| `S3_ARTIFACTS_BUCKET` | Wheel 저장 S3 |
| `SERVER_BASE_PATH` | 서버 기본 경로 |
| `HEALTH_CHECK_URL` | 헬스체크 URL |
| `DISCORD_WEBHOOK` | 알림 웹훅 |

### **서버 환경변수 (.env)**

```bash
# /home/ubuntu/refit/app/ai/.env
GEMINI_API_KEY=your_api_key
DATABASE_URL=postgresql://...
```

---

## 📞 문의

- **팀**: Re-Fit DevOps
- **Repository**: https://github.com/100-hours-a-week/19-team-project-ai