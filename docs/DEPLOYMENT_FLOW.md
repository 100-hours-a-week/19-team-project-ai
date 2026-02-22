# Re-Fit AI 배포 흐름 가이드

## 1. Wheel 패키지란?

**Wheel**은 Python의 표준 **바이너리 배포 포맷**입니다.

- 확장자: `.whl`
- 구조: **ZIP 압축 파일** (내부에 Python 패키지 + 메타데이터)
- 용도: `pip install`로 설치 가능한 **빌드 결과물**

### Wheel 파일 구성 예시

```
refit_ai_service-0.1.0-py3-none-any.whl  (ZIP 구조)
├── ai_app/
│   ├── __init__.py
│   ├── api/
│   │   ├── main.py
│   │   └── endpoints/
│   ├── adapters/
│   │   └── llm_client.py
│   └── services/
├── refit_ai_service-0.1.0.dist-info/
│   ├── METADATA      # 패키지 이름, 버전, 의존성
│   └── RECORD        # 포함된 파일 목록
```

### Wheel 생성 과정 (CI)

1. `pyproject.toml` + `ai_app/` 소스 코드 기반으로 `python -m build --wheel` 실행
2. `dist/refit_ai_service-0.1.0-py3-none-any.whl` 생성
3. main 브랜치 push → CI `release-prod` → wheel 아티팩트 업로드

---

## 2. site-packages와 ai_app 디렉터리 관계

### site-packages란?

`pip install`이 패키지를 설치하는 **Python 표준 위치**입니다.

```
/home/ubuntu/refit/app/ai/venv/
├── bin/
│   ├── python
│   └── pip
├── lib/
│   └── python3.11/
│       └── site-packages/    ← pip이 설치하는 곳
│           ├── ai_app/       ← wheel 설치 시 여기 생성됨
│           │   ├── __init__.py
│           │   ├── api/
│           │   ├── adapters/
│           │   └── ...
│           ├── fastapi/
│           ├── uvicorn/
│           └── ...
```

- **site-packages/ai_app/** = pip이 wheel을 풀어서 넣은 **최신 배포 코드**
- Python이 `import ai_app` 할 때 이 경로를 참조

### ai_app 디렉터리 (PM2 실행 경로)

```
/home/ubuntu/refit/app/ai/
├── venv/
├── ai_app/           ← PM2가 실제로 실행하는 코드 위치
│   ├── api/
│   │   └── main.py
│   ├── adapters/
│   └── ...
```

**PM2 ecosystem 설정:**
- `cwd`: `/home/ubuntu/refit/app/ai/ai_app`
- `PYTHONPATH`: `/home/ubuntu/refit/app/ai/ai_app`
- → uvicorn이 **이 디렉터리의 코드**를 로드해서 서버 실행

### 수정 전 문제 (두 경로 불일치)

| 경로 | 업데이트 여부 | 실제 사용 |
|------|---------------|-----------|
| site-packages/ai_app | ✅ CD 시 pip install로 매번 갱신 | ❌ 사용 안 함 |
| ai_app/ | ❌ CD에서 갱신 안 함 | ✅ PM2가 실행 |

→ CD가 돌아도 **PM2는 옛날 ai_app 코드**를 계속 실행함.

---

## 3. 배포 파이프라인 전체 흐름

### 3.1 CI (main 브랜치 push 시)

```
[개발자] develop → main 머지
    ↓
[CI] release-prod Job
    ├── checkout main
    ├── uv sync, pytest
    ├── python -m build --wheel
    ├── artifact: ai-wheel-{sha}
    └── cd-prod.yml 워크플로우 트리거
```

### 3.2 CD (cd-prod.yml)

```
[CD] deploy Job
    │
    ├── 1. main 브랜치의 최신 CI 아티팩트 찾기
    │
    ├── 2. GitHub Actions → S3 업로드
    │       wheel 파일 → s3://{bucket}/artifacts/ai/{sha}/xxx.whl
    │
    ├── 3. SSM으로 EC2에 배포 스크립트 전송
    │
    └── 4. EC2 서버에서 실행되는 스크립트
            │
            ├── S3에서 wheel 다운로드
            ├── 기존 ai_app 백업
            ├── pip install wheel.whl --force-reinstall
            │       → site-packages/ai_app 갱신
            │
            ├── ★ 추가: site-packages/ai_app → ai_app/ 동기화
            │       → PM2 실행 경로를 최신 코드로 맞춤
            │
            ├── PM2 재시작
            └── 헬스체크
```

### 3.3 수정 후 동기화 단계 (핵심)

```bash
# pip install 성공 후
AI_APP_SOURCE=$(python -c "import ai_app; import os; print(os.path.dirname(ai_app.__file__))")
# 예: /home/ubuntu/refit/app/ai/venv/lib/python3.11/site-packages/ai_app

rsync -a --delete "$AI_APP_SOURCE/" "$AI_APP_DIR/"
# site-packages/ai_app/ 내용을 ai_app/에 그대로 복사 (삭제된 파일도 반영)
```

- `--delete`: 소스에 없는 파일은 대상에서 삭제 (완전 동기화)
- Python 버전에 상관없이 `ai_app.__file__`로 실제 경로 조회

---

## 4. 서버에서 최신 코드가 적용되는 원리

1. **main 브랜치 머지** → CI가 해당 커밋으로 wheel 빌드
2. **wheel 업로드** → S3에 `artifacts/ai/{sha}/xxx.whl` 저장
3. **CD 실행** → SSM으로 서버에 배포
4. **pip install** → wheel 내용이 `venv/lib/pythonX.X/site-packages/ai_app/`에 설치
5. **동기화** → site-packages/ai_app → `/home/ubuntu/refit/app/ai/ai_app/` 복사
6. **PM2 재시작** → 새로 복사된 ai_app 코드로 서버 실행

이 흐름으로 **배포할 때마다 서버가 최신 main 코드**를 실행하게 됩니다.

---

## 5. 요약

| 항목 | 설명 |
|------|------|
| Wheel | Python 바이너리 배포 포맷 (ZIP), `pip install`로 설치 |
| site-packages | venv 안 패키지 설치 경로, pip이 wheel을 여기에 풀어 넣음 |
| ai_app/ | PM2가 cwd/PYTHONPATH로 사용하는 실제 실행 경로 |
| 수정 내용 | pip install 후 site-packages/ai_app를 ai_app/로 복사 |
| 결과 | main 머지 → CD → 서버 ai_app 갱신 → PM2가 최신 코드 실행 |
