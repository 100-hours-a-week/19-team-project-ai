#!/bin/bash
set -euo pipefail

MODE=${1:-normal}  # normal 또는 peak
REGION=${AWS_REGION:-ap-northeast-2}
NAMESPACE="ReFit/AI"
ENVIRONMENT=${ENVIRONMENT:-production}

# 시간 범위 설정 (최근 10분)
END_TIME=$(date -u +%Y-%m-%dT%H:%M:%S)
START_TIME=$(date -u -v-10M +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S)

echo "============================================"
echo "AI SLO 검증 시작 (CloudWatch)"
echo "모드: $MODE"
echo "기간: $START_TIME ~ $END_TIME"
echo "============================================"

# CloudWatch에서 메트릭 조회
get_metric_stat() {
  local metric_name=$1
  local stat_type=$2  # Average, SampleCount, Sum 등
  local dimensions=$3  # 선택적 dimensions

  aws cloudwatch get-metric-statistics \
    --namespace "$NAMESPACE" \
    --metric-name "$metric_name" \
    --start-time "$START_TIME" \
    --end-time "$END_TIME" \
    --period 600 \
    --statistics "$stat_type" \
    ${dimensions:+--dimensions $dimensions} \
    --region "$REGION" \
    --query "Datapoints[0].$stat_type" \
    --output text 2>/dev/null || echo "None"
}

# P95 조회 (ExtendedStatistics 사용)
get_metric_p95() {
  local metric_name=$1
  local dimensions=$2

  aws cloudwatch get-metric-statistics \
    --namespace "$NAMESPACE" \
    --metric-name "$metric_name" \
    --start-time "$START_TIME" \
    --end-time "$END_TIME" \
    --period 600 \
    --extended-statistics p95 \
    ${dimensions:+--dimensions $dimensions} \
    --region "$REGION" \
    --query 'Datapoints[0]."p95"' \
    --output text 2>/dev/null || echo "None"
}

# 가용성 계산
calculate_availability() {
  local endpoint=$1
  local dim="Name=Endpoint,Value=$endpoint Name=Environment,Value=$ENVIRONMENT"
  
  local success=$(get_metric_stat "RequestCount" "Sum" "$dim Name=StatusCode,Value=2xx")
  local total=$(get_metric_stat "RequestCount" "Sum" "$dim")
  local rate_limit=$(get_metric_stat "RequestCount" "Sum" "$dim Name=StatusCode,Value=429")
  
  if [ "$success" = "None" ] || [ "$total" = "None" ]; then
    echo "None"
    return
  fi
  
  # Rate Limit 제외한 Valid Events
  local valid_events=$total
  if [ "$rate_limit" != "None" ] && [ -n "$rate_limit" ]; then
    valid_events=$((total - rate_limit))
  fi
  
  # 가용성 계산 (%)
  if [ "$valid_events" -gt 0 ]; then
    awk -v s="$success" -v v="$valid_events" 'BEGIN{printf "%.2f", (s/v)*100}'
  else
    echo "None"
  fi
}

# SLO 임계값 정의 (SLI/SLO 문서 기준)
if [ "$MODE" = "peak" ]; then
  # 피크 시즌 완화된 SLO
  RECO_LATENCY_THRESHOLD=5000        # 3초 → 5초
  RECO_AVAILABILITY_THRESHOLD=98.0   # 99% → 98%
  DOC_LATENCY_THRESHOLD=45000        # 30초 → 45초
  DOC_AVAILABILITY_THRESHOLD=98.0    # 99% → 98%
  REPORT_LATENCY_THRESHOLD=100000    # 70초 → 100초
  REPORT_AVAILABILITY_THRESHOLD=97.0 # 98% → 97%
else
  # 평시 SLO (SLI/SLO 문서 기준)
  RECO_LATENCY_THRESHOLD=3000        # P95 < 3초
  RECO_AVAILABILITY_THRESHOLD=99.0   # 99.0%
  DOC_LATENCY_THRESHOLD=30000        # P95 < 30초
  DOC_AVAILABILITY_THRESHOLD=99.0    # 99.0%
  REPORT_LATENCY_THRESHOLD=70000     # P95 < 70초
  REPORT_AVAILABILITY_THRESHOLD=98.0 # 98.0%
fi

# 메트릭 검증
check_latency() {
  local endpoint=$1
  local threshold=$2
  local friendly_name=$3
  
  local dim="Name=Endpoint,Value=$endpoint Name=Environment,Value=$ENVIRONMENT"
  local actual=$(get_metric_p95 "ResponseTime" "$dim")

  if [ "$actual" = "None" ] || [ -z "$actual" ]; then
    echo "  ⚠️  $friendly_name 응답시간: 데이터 없음 (충분한 트래픽 필요)"
    return 0  # 데이터 없으면 통과로 처리
  fi

  # 밀리초로 변환 (CloudWatch는 초 단위로 저장 가능)
  local actual_ms=$(awk -v a="$actual" 'BEGIN{printf "%.0f", a*1000}')
  local threshold_ms=$(awk -v t="$threshold" 'BEGIN{printf "%.0f", t}')

  if awk -v a="$actual_ms" -v t="$threshold_ms" 'BEGIN{exit !(a > t)}'; then
    echo "  ❌ $friendly_name 응답시간: ${actual_ms}ms > ${threshold_ms}ms"
    return 1
  else
    echo "  ✅ $friendly_name 응답시간: ${actual_ms}ms <= ${threshold_ms}ms"
    return 0
  fi
}

check_availability() {
  local endpoint=$1
  local threshold=$2
  local friendly_name=$3
  
  local actual=$(calculate_availability "$endpoint")

  if [ "$actual" = "None" ] || [ -z "$actual" ]; then
    echo "  ⚠️  $friendly_name 가용성: 데이터 없음 (충분한 트래픽 필요)"
    return 0
  fi

  if awk -v a="$actual" -v t="$threshold" 'BEGIN{exit !(a < t)}'; then
    echo "  ❌ $friendly_name 가용성: ${actual}% < ${threshold}%"
    return 1
  else
    echo "  ✅ $friendly_name 가용성: ${actual}% >= ${threshold}%"
    return 0
  fi
}

# 실제 구현된 AI API 검증
FAILED=0

echo ""
echo "📊 API 1: 멘토 추천 (GET /api/ai/mentors/recommend/)"
# 동적 경로 (/mentors/recommend/{user_id})는 CloudWatch에서 집계하기 어려우므로
# 전체 /api/ai/mentors로 검증
check_latency "/api/ai/mentors/recommend" "$RECO_LATENCY_THRESHOLD" "멘토 추천 API" || FAILED=1
check_availability "/api/ai/mentors/recommend" "$RECO_AVAILABILITY_THRESHOLD" "멘토 추천 API" || FAILED=1

echo ""
echo "📊 API 2: 이력서 파싱 (POST /api/ai/resumes/{task_id}/parse)"
# 동적 경로는 /api/ai/resumes로 집계
check_latency "/api/ai/resumes" "$DOC_LATENCY_THRESHOLD" "이력서 파싱 API" || FAILED=1
check_availability "/api/ai/resumes" "$DOC_AVAILABILITY_THRESHOLD" "이력서 파싱 API" || FAILED=1

echo ""
echo "📊 API 3: 채용공고 파싱 (POST /api/ai/jobs/parse)"
check_latency "/api/ai/jobs" "$REPORT_LATENCY_THRESHOLD" "채용공고 파싱 API" || FAILED=1
check_availability "/api/ai/jobs" "$REPORT_AVAILABILITY_THRESHOLD" "채용공고 파싱 API" || FAILED=1

# Error Budget 소진율 확인 (선택적)
echo ""
echo "📊 Error Budget 상태:"
for endpoint in "/api/ai/mentors/recommend" "/api/ai/resumes" "/api/ai/jobs"; do
  availability=$(calculate_availability "$endpoint")
  
  if [ "$availability" = "None" ]; then
    # 엔드포인트 이름 간단하게 표시
    endpoint_name=$(echo "$endpoint" | sed 's|/api/ai/||g' | sed 's|/.*||g')
    echo "  ⚠️  $endpoint_name: 데이터 없음"
    continue
  fi
  
  # SLO에 따른 Error Budget 계산 (모두 99% 목표)
  slo=99.0
  
  # Error Budget 소진율 = (100 - 실제) / (100 - SLO) * 100
  burn_rate=$(awk -v a="$availability" -v s="$slo" 'BEGIN{printf "%.1f", (100-a)/(100-s)*100}')
  
  # 엔드포인트 이름 간단하게 표시
  endpoint_name=$(echo "$endpoint" | sed 's|/api/ai/||g' | sed 's|/.*||g')
  
  if awk -v b="$burn_rate" 'BEGIN{exit !(b > 100)}'; then
    echo "  🔴 $endpoint_name: Error Budget ${burn_rate}% 소진 (초과!)"
    FAILED=1
  elif awk -v b="$burn_rate" 'BEGIN{exit !(b > 75)}'; then
    echo "  🟠 $endpoint_name: Error Budget ${burn_rate}% 소진 (경고)"
  elif awk -v b="$burn_rate" 'BEGIN{exit !(b > 50)}'; then
    echo "  🟡 $endpoint_name: Error Budget ${burn_rate}% 소진 (주의)"
  else
    echo "  🟢 $endpoint_name: Error Budget ${burn_rate}% 소진 (건강)"
  fi
done

echo ""
echo "============================================"

if [ $FAILED -eq 1 ]; then
  echo "⚠️  SLO 위반 감지됨 (경고 모드)"
  echo "   배포는 계속되지만 성능 개선이 필요합니다."
  echo "============================================"
  exit 0  # 초기에는 경고만, 향후 exit 1로 변경하여 배포 차단
fi

echo "✅ 모든 SLO 검증 통과!"
echo "============================================"
exit 0
