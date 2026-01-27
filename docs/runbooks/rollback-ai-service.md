# Re-Fit AI 서비스 수동 롤백 Runbook

> **목적**: AI 서비스 장애 발생 시 신속한 롤백을 위한 실행 가이드  
> **대상**: DevOps 팀, Backend 개발자  
> **최종 수정**: 2024-01-27

---

## 🚨 긴급 연락망

| 역할 | 담당자 | 연락처 | Discord |
|------|--------|--------|---------|
| 1차 대응 (DevOps) | 담당자명 | 010-XXXX-XXXX | @devops-oncall |
| 2차 대응 (AI Backend) | 담당자명 | 010-YYYY-YYYY | @ai-backend-lead |
| 최종 에스컬레이션 | CTO | 010-ZZZZ-ZZZZ | @cto |

**알림 채널**: `#ai-service-alerts` (자동), `#incident-response` (수동 보고)

---

## 📊 장애 심각도 분류

### 🔴 P0 (Critical) - 즉시 롤백
- AI 응답 완전 중단 (5분 이상)
- 5xx 에러율 > 50%
- 데이터베이스 연결 실패
- 전체 서버 다운

**대응 시간**: 즉시 (5분 이내)  
**조치**: 즉시 롤백 후 원인 파악

### 🟡 P1 (High) - 긴급 대응
- AI 응답률 < 50%
- 평균 응답 시간 > 30초
- 5xx 에러율 10-50%
- AI 모델 API 타임아웃 급증

**대응 시간**: 15분 이내  
**조치**: 원인 파악 후 롤백 또는 Hot Fix

### 🟢 P2 (Medium) - 모니터링
- AI 응답 시간 증가 (10-30초)
- 간헐적 오류 발생
- 5xx 에러율 3-10%

**대응 시간**: 1시간 이내  
**조치**: 모니터링 후 필요 시 롤백

---

## 🔍 장애 감지 및 판단

### STEP 1: Discord 알림 확인

**알림 예시**:
```
🚨 [P0] High Error Rate
Metric: 5xx Error Rate > 50%
Time: 2024-01-27 14:23:00
Server: ip-172-31-xx-xx
```

### STEP 2: 즉시 실행할 확인 명령어

```bash
# 1. 서버 접속
ssh ec2-user@your-server-ip

# 2. AI 백엔드 헬스 체크
curl http://localhost:8080/actuator/health

# 3. PM2 프로세스 상태
pm2 status

# 4. 최근 에러 로그 확인 (최근 50줄)
tail -n 50 /var/log/app/application.log | grep ERROR

# 5. AI 요청 테스트
curl -X POST http://localhost:8080/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TEST_TOKEN" \
  -d '{
    "message": "헬스체크 테스트",
    "conversationId": "health-check-001"
  }'
```

### STEP 3: 장애 심각도 판단

#### ✅ 즉시 롤백이 필요한 경우 (P0)
- [ ] `/actuator/health` 응답 실패 또는 status != "UP"
- [ ] PM2 프로세스 `errored` 또는 `stopped` 상태
- [ ] 에러 로그에 "NullPointerException", "OutOfMemoryError" 등 심각한 에러
- [ ] AI 요청 테스트 실패 또는 30초 이상 소요

**→ 체크박스 1개 이상 해당 시 즉시 [P0 롤백 프로세스](#p0-롤백-프로세스-전체-서비스-중단)로 이동**

#### ⚠️ 모니터링이 필요한 경우 (P1/P2)
- [ ] 헬스체크는 통과하나 응답 시간 > 10초
- [ ] 간헐적 에러 발생 (에러율 < 10%)
- [ ] 특정 기능만 오류

**→ [P1 롤백 프로세스](#p1-롤백-프로세스-ai-응답-품질-저하)로 이동하여 추가 분석**

---

## 🔄 P0 롤백 프로세스 (전체 서비스 중단)

### 실행 체크리스트

#### ☐ STEP 1: 장애 공지 (1분)

**Discord #incident-response 채널에 즉시 공지**:
```
🚨 [P0 긴급] AI 서비스 장애 발생

발생 시간: [현재 시간]
증상: AI 응답 불가 / 서버 다운
조치: 즉시 롤백 진행 중
담당자: @본인이름
예상 복구: 5-10분 이내
```

#### ☐ STEP 2: 사용 가능한 안정 버전 확인 (1분)

```bash
# 서버에서 실행
ls -lht /opt/ai_app/releases/

# 출력 예시:
# drwxr-xr-x 3 ec2-user ec2-user 4.0K Jan 27 15:03 v20240127-150300  <- 현재(문제)
# drwxr-xr-x 3 ec2-user ec2-user 4.0K Jan 27 12:00 v20240127-120000  <- 이전 안정
# drwxr-xr-x 3 ec2-user ec2-user 4.0K Jan 26 18:00 v20240126-180000
# lrwxrwxrwx 1 ec2-user ec2-user   40 Jan 27 15:03 current -> releases/v20240127-150300
```

**안정 버전 선택 기준**:
- 가장 최근 배포된 버전에서 한 단계 이전 버전
- 위 예시의 경우: `v20240127-120000` 선택

#### ☐ STEP 3: 롤백 실행 (2분)

```bash
# 방법 1: 서버에서 직접 실행
cd /opt/scripts
sudo ./rollback.sh backend 20240127-120000

# 방법 2: 로컬에서 원격 실행 (SSM 사용)
./rollback-remote.sh backend 20240127-120000
```

**실행 중 확인 사항**:
- ✅ "Rollback Start" 메시지 확인
- ✅ "Switching to version v20240127-120000" 확인
- ✅ "Restarting backend with PM2" 확인
- ✅ 헬스체크 진행 (10회 시도)

#### ☐ STEP 4: 서비스 복구 검증 (2분)

```bash
# 1. 헬스 체크 (반복 실행하여 안정화 확인)
for i in {1..5}; do
  echo "=== Check $i/5 ==="
  curl -s http://localhost:8080/actuator/health | jq '.status'
  sleep 2
done

# 기대 출력: "UP" (5번 모두)

# 2. AI 기능 테스트
curl -X POST http://localhost:8080/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TEST_TOKEN" \
  -d '{
    "message": "안녕하세요",
    "conversationId": "rollback-test-001"
  }' | jq '.response'

# 기대 출력: AI 응답 정상 반환

# 3. PM2 상태 확인
pm2 status
# 기대 출력: backend 상태 "online", restart 0-1회

# 4. 최근 에러 로그 확인
tail -n 20 /var/log/app/application.log | grep ERROR
# 기대 출력: 새로운 에러 없음
```

#### ☐ STEP 5: 복구 완료 공지 (1분)

**모든 검증 통과 시 Discord 공지**:
```
✅ [P0 해결] AI 서비스 복구 완료

복구 시간: [현재 시간]
장애 시간: [발생 시간 - 복구 시간] (약 X분)
조치 내역: 
  - 롤백: v20240127-150300 → v20240127-120000
  - 상태: 헬스체크 통과, AI 응답 정상
  
다음 단계:
  - 원인 분석 진행 예정
  - 인시던트 보고서 작성 예정
```

---

## 🔧 P1 롤백 프로세스 (AI 응답 품질 저하)

### 실행 체크리스트

#### ☐ STEP 1: 상세 증상 확인 (3분)

```bash
# 1. 최근 AI 응답 로그 샘플링 (20건)
tail -n 20 /var/log/app/ai-responses.log

# 확인 사항:
# - 응답이 무의미한가?
# - 동일한 응답 반복?
# - 컨텍스트 유실?
# - 에러 메시지 포함?

# 2. AI 응답 품질 메트릭 확인
psql -h localhost -U dbuser -d aiservice << EOF
SELECT 
  created_at,
  user_message,
  LEFT(ai_response, 100) as response_preview,
  response_time_ms,
  tokens_used
FROM ai_requests
WHERE created_at > NOW() - INTERVAL '30 minutes'
ORDER BY created_at DESC
LIMIT 10;
EOF

# 3. 최근 배포 변경사항 확인
cd /opt/ai_app
git log -5 --oneline --all

# 4. AI 모델 설정 확인
curl http://localhost:8080/api/v1/model/info
```

#### ☐ STEP 2: 롤백 여부 결정

**즉시 롤백 조건** (하나라도 해당 시):
- [ ] 최근 1시간 내 배포 있음
- [ ] AI 응답 품질 저하가 전체 요청의 30% 이상
- [ ] 프롬프트 템플릿 또는 모델 설정 변경 확인
- [ ] 빠른 수정 불가능 (30분 이내 Hot Fix 불가)

**모니터링 지속 조건**:
- [ ] 간헐적 오류 (< 30%)
- [ ] 특정 유형의 질문에만 문제
- [ ] Hot Fix 가능

#### ☐ STEP 3: 롤백 실행 (즉시 롤백 조건 충족 시)

```bash
# 이전 안정 버전으로 롤백
sudo /opt/scripts/rollback.sh backend [이전_버전]

# 예: sudo /opt/scripts/rollback.sh backend 20240127-120000
```

#### ☐ STEP 4: 롤백 후 품질 검증 (5분)

```bash
# 1. 다양한 테스트 케이스 실행
# 테스트 케이스 1: 일반 대화
curl -X POST http://localhost:8080/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TEST_TOKEN" \
  -d '{
    "message": "운동 루틴을 추천해주세요",
    "conversationId": "test-001"
  }' | jq '.response'

# 테스트 케이스 2: 컨텍스트 유지 확인
curl -X POST http://localhost:8080/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TEST_TOKEN" \
  -d '{
    "message": "좀 더 자세히 설명해줘",
    "conversationId": "test-001"
  }' | jq '.response'

# 테스트 케이스 3: 긴 질문 처리
curl -X POST http://localhost:8080/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TEST_TOKEN" \
  -d '{
    "message": "나는 30대 남성이고 체중 감량이 목표야. 헬스장에 주 3회 갈 수 있고, 집에서도 운동하고 싶어. 무릎에 부담이 적은 운동으로 3개월 루틴을 만들어줘.",
    "conversationId": "test-002"
  }' | jq '.response'

# 2. 응답 품질 육안 확인
# - 의미 있는 답변인가?
# - 컨텍스트를 유지하는가?
# - 응답 시간이 적절한가? (< 10초)

# 3. 에러 로그 확인
tail -n 50 /var/log/app/application.log | grep -E "ERROR|WARN"
```

#### ☐ STEP 5: Discord 공지

**롤백 완료 시**:
```
⚠️ [P1 해결] AI 응답 품질 이슈 해결

조치: 이전 버전으로 롤백 완료
롤백 버전: v20240127-120000
검증: 테스트 케이스 통과
상태: AI 응답 정상

다음 단계: 문제 버전 분석 진행
```

---

## 🐌 P2 롤백 프로세스 (AI 응답 속도 저하)

### 실행 체크리스트

#### ☐ STEP 1: 병목 지점 파악 (5분)

```bash
# 1. Application 레벨 응답 시간 확인
curl http://localhost:8080/actuator/metrics/http.server.requests | jq '
  .measurements[] | 
  select(.statistic == "TOTAL_TIME") | 
  .value
'

# 2. AI 모델 API 응답 시간 직접 측정
time curl -X POST http://ai-model-service:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "테스트"}]
  }'

# 3. 데이터베이스 슬로우 쿼리 확인
psql -h localhost -U dbuser -d aiservice << EOF
SELECT 
  query,
  calls,
  total_exec_time,
  mean_exec_time,
  max_exec_time
FROM pg_stat_statements
WHERE mean_exec_time > 100
ORDER BY mean_exec_time DESC
LIMIT 10;
EOF

# 4. 시스템 리소스 확인
echo "=== CPU/Memory ==="
top -b -n 1 | head -20

echo "=== Disk I/O ==="
iostat -x 1 3

echo "=== Memory ==="
free -m

# 5. PM2 메모리 사용량
pm2 status
pm2 monit  # 실시간 모니터링 (Ctrl+C로 종료)
```

#### ☐ STEP 2: 원인 분류 및 대응

**원인별 즉시 조치**:

##### Case 1: AI 모델 API 응답 느림 (>10초)
```bash
# 확인
time curl -X POST [AI_MODEL_API_URL]

# 대응
# 1. 타임아웃 설정 확인
# 2. 캐시 활성화 상태 확인
# 3. 최근 모델 변경 있었는지 확인 → 있다면 롤백 고려
```

##### Case 2: 데이터베이스 쿼리 느림
```bash
# 확인
# 슬로우 쿼리 로그에서 100ms 이상 쿼리 확인

# 대응
# 1. 즉시: 인덱스 추가
# 2. 최근 스키마 변경 있었다면 → 롤백
```

##### Case 3: 서버 리소스 부족 (CPU/Memory > 90%)
```bash
# 확인
top -b -n 1 | head -5

# 대응
# 1. 즉시: PM2 재시작
pm2 restart backend

# 2. 메모리 누수 의심 시 → 롤백
# 3. 재시작 후에도 지속되면 → 롤백
```

#### ☐ STEP 3: 롤백 결정 및 실행

**롤백이 필요한 경우**:
- [ ] 최근 배포 후 성능 저하 시작
- [ ] PM2 재시작으로 해결 안 됨
- [ ] 코드 레벨 최적화 필요 (즉시 수정 불가)

```bash
# 롤백 실행
sudo /opt/scripts/rollback.sh backend [이전_버전]

# 롤백 후 성능 비교
# Before: 평균 응답 시간 30초
# After: 평균 응답 시간 5초
# → 성능 개선 확인 시 롤백 유지
```

#### ☐ STEP 4: 성능 검증

```bash
# Apache Bench로 부하 테스트
ab -n 50 -c 5 \
  -p test-payload.json \
  -T application/json \
  http://localhost:8080/api/v1/ai/chat

# 출력에서 확인:
# - Requests per second (높을수록 좋음)
# - Time per request (낮을수록 좋음)
# - Failed requests (0이어야 함)
```

---

## 📝 롤백 후 필수 작업

### ✅ 기술 검증 체크리스트

```bash
# 1. 헬스 체크
curl http://localhost:8080/actuator/health | jq '.'
# 기대: {"status": "UP"}

# 2. AI 채팅 테스트
curl -X POST http://localhost:8080/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TEST_TOKEN" \
  -d '{"message": "테스트", "conversationId": "post-rollback-test"}' \
  | jq '.'
# 기대: 정상 응답

# 3. 대화 히스토리 조회
curl http://localhost:8080/api/v1/conversations/post-rollback-test \
  -H "Authorization: Bearer TEST_TOKEN" | jq '.'
# 기대: 이전 대화 내역 조회 가능

# 4. 데이터베이스 연결
psql -h localhost -U dbuser -d aiservice -c \
  "SELECT COUNT(*) FROM ai_requests WHERE created_at > NOW() - INTERVAL '1 hour';"
# 기대: 정상 실행

# 5. PM2 프로세스
pm2 status
# 기대: backend 상태 "online", restart 0-1회

# 6. 에러 로그
tail -n 100 /var/log/app/application.log | grep ERROR
# 기대: 새로운 에러 없음

# 7. 시스템 리소스
free -m && df -h
# 기대: 여유 공간 충분
```

### 📋 비즈니스 검증 체크리스트

- [ ] 신규 대화 생성 가능
- [ ] 기존 대화 이어가기 가능
- [ ] AI 응답 품질 정상 (의미 있는 답변)
- [ ] 응답 속도 정상 (< 10초)
- [ ] 컨텍스트 유지 정상
- [ ] 토큰 사용량 정상 계산
- [ ] 대화 히스토리 저장/조회 정상

### 📊 모니터링 확인 (10분간)

```bash
# 실시간 에러 모니터링
watch -n 5 'tail -20 /var/log/app/application.log | grep ERROR'

# PM2 실시간 모니터링
pm2 monit

# 헬스체크 반복 (10분간)
watch -n 30 'curl -s http://localhost:8080/actuator/health | jq ".status"'
```

---

## 📄 사후 처리

### 1. 인시던트 보고서 작성 (1시간 이내)

**템플릿**: `/docs/incident-report-template.md` 사용

**필수 포함 내용**:
- 인시던트 ID: `INC-YYYYMMDD-XXX`
- 타임라인 (발생-감지-조치-복구)
- 근본 원인 (Root Cause)
- 영향 범위 (사용자 수, 요청 실패 수)
- 재발 방지 대책

### 2. Discord 최종 보고

```
📋 [인시던트 최종 보고] INC-20240127-001

장애 시간: 15:07 - 15:13 (6분)
심각도: P0
근본 원인: [간단한 원인 요약]

타임라인:
  15:05 - 배포 (v20240127-150300)
  15:07 - 장애 감지
  15:09 - 롤백 시작
  15:13 - 서비스 복구

재발 방지:
  - [조치 1]
  - [조치 2]

상세 보고서: [링크]
```

### 3. 문제 버전 분석 (24시간 이내)

```bash
# 로컬 환경에서 문제 버전 분석
git checkout v20240127-150300
git checkout -b hotfix/inc-20240127-001

# 문제 재현 시도
# 원인 파악
# 수정 및 테스트
# PR 생성
```

### 4. 회고 미팅 예약 (1주일 이내)

**참석자**: DevOps, Backend, PM  
**안건**:
- 무엇이 잘됐나?
- 무엇을 개선할 수 있나?
- 액션 아이템 도출

---

## 🔧 트러블슈팅 가이드

### ❌ 문제: 롤백 스크립트가 실패함

```bash
# 증상
./rollback.sh backend 20240127-120000
Error: Version not found

# 해결 1: 버전 경로 확인
ls -la /opt/ai_app/releases/
# v20240127-120000 디렉토리가 실제로 존재하는지 확인

# 해결 2: 수동 롤백
cd /opt/ai_app
ln -sfn ./releases/v20240127-120000 current
pm2 restart backend
pm2 save
```

### ❌ 문제: 롤백 후에도 헬스체크 실패

```bash
# 증상
curl http://localhost:8080/actuator/health
curl: (7) Failed to connect

# 해결 1: PM2 로그 확인
pm2 logs backend --lines 50

# 해결 2: 포트 사용 확인
netstat -tulpn | grep 8080

# 해결 3: 프로세스 강제 재시작
pm2 delete backend
pm2 start /opt/ai_app/ecosystem.config.js
```

### ❌ 문제: 데이터베이스 연결 실패

```bash
# 증상
ERROR: connection to server failed

# 해결 1: PostgreSQL 상태 확인
sudo systemctl status postgresql
pg_isready -h localhost -p 5432

# 해결 2: 연결 정보 확인
cat /opt/ai_app/current/.env | grep DB_

# 해결 3: PostgreSQL 재시작
sudo systemctl restart postgresql
```

### ❌ 문제: 롤백 후 이전 대화 내역 조회 안 됨

```bash
# 증상
대화 히스토리 API 호출 시 404 또는 500 에러

# 원인 확인: 데이터베이스 마이그레이션 이슈
psql -h localhost -U dbuser -d aiservice -c "\d+ ai_requests"

# 해결: 데이터베이스는 롤백하지 않고 앱만 롤백
# 데이터베이스 스키마는 하위 호환성 유지되어야 함
# 마이그레이션 문제 발생 시 즉시 에스컬레이션
```

---

## 📚 빠른 참조

### 주요 명령어 치트시트

```bash
# === 상태 확인 ===
curl http://localhost:8080/actuator/health
pm2 status
tail -f /var/log/app/application.log

# === 롤백 ===
sudo /opt/scripts/rollback.sh backend [버전]

# === 버전 확인 ===
ls -lht /opt/ai_app/releases/
cat /opt/ai_app/current/version.txt

# === 로그 ===
tail -n 100 /var/log/app/application.log | grep ERROR
pm2 logs backend --lines 50

# === 재시작 ===
pm2 restart backend
pm2 restart all
```

### 주요 파일 경로

```
/opt/ai_app/                          # AI 앱 루트
/opt/ai_app/current/                  # 현재 버전 (심볼릭 링크)
/opt/ai_app/releases/                 # 모든 버전
/opt/scripts/rollback.sh              # 롤백 스크립트
/var/log/app/application.log          # 애플리케이션 로그
/var/log/pm2/backend-error.log        # PM2 에러 로그
/etc/environment                      # 환경변수
```

### Discord Webhook 테스트

```bash
# 알림 테스트
/opt/scripts/discord-notify.sh "P2" "테스트 알림" "이것은 테스트 메시지입니다"
```

---

## 📋 체크리스트 요약

### P0 긴급 롤백 (5-10분)
- [ ] Discord 장애 공지
- [ ] 서버 접속 및 상태 확인
- [ ] 안정 버전 확인
- [ ] 롤백 실행
- [ ] 서비스 검증 (헬스체크, AI 테스트)
- [ ] Discord 복구 공지
- [ ] 모니터링 (10분)
- [ ] 인시던트 보고서 작성

### P1 품질 저하 (15-30분)
- [ ] 증상 상세 확인 (로그, 메트릭, Git)
- [ ] 롤백 여부 결정
- [ ] 롤백 실행 (필요 시)
- [ ] 품질 검증 (테스트 케이스)
- [ ] Discord 공지
- [ ] 원인 분석 시작

### P2 성능 저하 (30-60분)
- [ ] 병목 지점 파악 (App, DB, 시스템)
- [ ] 원인별 즉시 조치
- [ ] 롤백 필요 시 실행
- [ ] 성능 테스트
- [ ] Discord 공지

---

## 🔄 이 문서의 업데이트

**변경 이력**:
- 2024-01-27: 초안 작성 (v1.0)

**다음 리뷰**: 2024-02-27

**개선 제안**: `#ai-service-alerts` 채널에 피드백 남기기

---

## 📞 추가 도움이 필요한 경우

1. **Discord**: `#incident-response` 채널에 `@devops-oncall` 멘션
2. **긴급 전화**: 1차 대응자에게 직접 연락
3. **에스컬레이션**: 30분 내 해결 안 되면 2차 대응자/CTO에게 보고
