# CloudWatch 메트릭 설정 가이드

## 📊 개요

AI 서비스의 SLI/SLO 모니터링을 위해 FastAPI Middleware를 통해 CloudWatch로 메트릭을 전송합니다.

---

## 🔧 1. IAM 권한 설정

### 필요한 권한

EC2 인스턴스의 IAM Role에 다음 권한 추가:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "cloudwatch:PutMetricData"
      ],
      "Resource": "*"
    }
  ]
}
```

### 적용 방법

1. **AWS Console → IAM → Roles**
2. EC2 인스턴스에 연결된 Role 찾기
3. **Permissions 탭 → Add permissions → Attach policies**
4. `CloudWatchAgentServerPolicy` 정책 연결 (권장)
   - 또는 위 JSON으로 인라인 정책 추가

---

## 🚀 2. 환경 변수 설정

### 서버의 `.env` 파일에 추가

```bash
# CloudWatch 메트릭 설정
CLOUDWATCH_METRICS_ENABLED=true
ENVIRONMENT=production
AWS_REGION=ap-northeast-2

# AWS 자격 증명 (EC2 IAM Role 사용 시 불필요)
# AWS_ACCESS_KEY_ID=your_access_key
# AWS_SECRET_ACCESS_KEY=your_secret_key
```

### 환경별 설정

| 환경 | CLOUDWATCH_METRICS_ENABLED | ENVIRONMENT |
|------|---------------------------|-------------|
| **프로덕션** | `true` | `production` |
| **스테이징** | `true` | `staging` |
| **개발 로컬** | `false` | `development` |

---

## 📈 3. 수집되는 메트릭

### Namespace: `ReFit/AI`

| 메트릭 이름 | 설명 | Unit | Dimensions |
|-----------|------|------|-----------|
| **ResponseTime** | API 응답 시간 (P95 계산용) | Milliseconds | Endpoint, Environment |
| **RequestCount** | 요청 수 (가용성 계산용) | Count | Endpoint, StatusCode, Environment |
| **ErrorCount** | 5xx 에러 수 | Count | Endpoint, Environment |

### Endpoint 예시

- `/api/ai/recommendations` (추천 API)
- `/api/ai/documents/analyze` (문서분석 API)
- `/api/ai/reports/generate` (리포트 API)

---

## 🔍 4. CloudWatch 대시보드 생성

### AWS Console에서 대시보드 생성

1. **CloudWatch → Dashboards → Create dashboard**
2. 대시보드 이름: `ReFit-AI`

### 추가할 위젯

#### 4.1 API 응답 시간 (P95)

```json
{
  "metrics": [
    [ "ReFit/AI", "ResponseTime", { "stat": "p95", "label": "추천 API P95" }, { "dimensions": { "Endpoint": "/api/ai/recommendations" } } ],
    [ "...", { "dimensions": { "Endpoint": "/api/ai/documents/analyze" } }, { "stat": "p95", "label": "문서분석 API P95" } ],
    [ "...", { "dimensions": { "Endpoint": "/api/ai/reports/generate" } }, { "stat": "p95", "label": "리포트 API P95" } ]
  ],
  "view": "timeSeries",
  "region": "ap-northeast-2",
  "title": "API 응답 시간 (P95)",
  "yAxis": {
    "left": {
      "label": "Milliseconds",
      "showUnits": false
    }
  }
}
```

#### 4.2 가용성

```json
{
  "metrics": [
    [ { "expression": "m1/(m1+m2)*100", "label": "추천 API 가용성", "id": "e1" } ],
    [ "ReFit/AI", "RequestCount", { "stat": "Sum", "id": "m1", "visible": false }, { "dimensions": { "Endpoint": "/api/ai/recommendations", "StatusCode": "2xx" } } ],
    [ "...", { "stat": "Sum", "id": "m2", "visible": false }, { "dimensions": { "Endpoint": "/api/ai/recommendations", "StatusCode": "5xx" } } ]
  ],
  "view": "singleValue",
  "region": "ap-northeast-2",
  "title": "가용성 (%)",
  "yAxis": {
    "left": {
      "min": 0,
      "max": 100
    }
  }
}
```

#### 4.3 요청 수 (트래픽)

```json
{
  "metrics": [
    [ "ReFit/AI", "RequestCount", { "stat": "Sum" }, { "dimensions": { "Endpoint": "/api/ai/recommendations" } } ],
    [ "...", { "dimensions": { "Endpoint": "/api/ai/documents/analyze" } } ],
    [ "...", { "dimensions": { "Endpoint": "/api/ai/reports/generate" } } ]
  ],
  "view": "timeSeries",
  "region": "ap-northeast-2",
  "title": "API 요청 수",
  "period": 300
}
```

#### 4.4 Error Budget 소진율

```json
{
  "metrics": [
    [ { "expression": "(100-m1)/(100-99)*100", "label": "추천 API Error Budget", "id": "e1" } ],
    [ "ReFit/AI", "RequestCount", { "stat": "Sum", "id": "m1", "visible": false }, { "dimensions": { "Endpoint": "/api/ai/recommendations", "StatusCode": "2xx" } } ]
  ],
  "view": "singleValue",
  "region": "ap-northeast-2",
  "title": "Error Budget 소진율 (%)"
}
```

---

## ✅ 5. 검증

### 5.1 로컬에서 확인

```bash
# 서버 시작
cd /home/ubuntu/refit/app/ai
source venv/bin/activate
uvicorn api.main:app --host 0.0.0.0 --port 8000

# 테스트 요청
curl -X POST http://localhost:8000/api/ai/recommendations \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "interest": "backend"}'
```

### 5.2 CloudWatch에서 확인

```bash
# AWS CLI로 메트릭 조회
aws cloudwatch get-metric-statistics \
  --namespace ReFit/AI \
  --metric-name ResponseTime \
  --start-time 2026-01-28T00:00:00Z \
  --end-time 2026-01-28T23:59:59Z \
  --period 300 \
  --statistics Average \
  --dimensions Name=Endpoint,Value=/api/ai/recommendations
```

### 5.3 로그 확인

```bash
# PM2 로그에서 CloudWatch 전송 확인
pm2 logs ai-service | grep -i cloudwatch
```

---

## 🐛 6. 트러블슈팅

### 문제: 메트릭이 CloudWatch에 나타나지 않음

**확인 사항:**
1. IAM 권한 확인
2. 환경 변수 `CLOUDWATCH_METRICS_ENABLED=true` 확인
3. PM2 로그에서 에러 확인
4. AWS 리전 확인 (`AWS_REGION=ap-northeast-2`)

### 문제: "Access Denied" 에러

**해결 방법:**
1. EC2 인스턴스의 IAM Role에 `cloudwatch:PutMetricData` 권한 추가
2. 또는 `.env`에 AWS 자격 증명 추가

### 문제: 메트릭 전송이 느려서 API 응답이 지연됨

**해결 방법:**
- Middleware는 이미 비동기로 설계되어 있어 응답에 영향 없음
- 만약 문제가 있다면 `CLOUDWATCH_METRICS_ENABLED=false`로 일시 비활성화

---

## 📊 7. CD 워크플로우와 연동

CloudWatch 검증이 자동으로 실행됩니다:

1. **배포 완료 후 10분 대기** (메트릭 수집)
2. **CloudWatch 검증 스크립트 실행** (`verify-slo-cloudwatch.sh`)
3. **SLO 위반 시 Discord 알림**

---

## 📚 참고 자료

- [AWS CloudWatch 메트릭 전송 가이드](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/publishingMetrics.html)
- [boto3 CloudWatch 문서](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudwatch.html)
- [SLI/SLO 정의서](./ReFit_AI_Service_SLI_SLO_4.md)
