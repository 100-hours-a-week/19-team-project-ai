#!/bin/bash
set -e

API_BASE_URL="${1:-http://localhost:8000}"
NUM_REQUESTS="${2:-100}"

echo "============================================"
echo "AI API 부하 테스트 (CloudWatch 메트릭 생성용)"
echo "============================================"
echo ""
echo "API Base URL: $API_BASE_URL"
echo "요청 횟수: $NUM_REQUESTS"
echo ""

SUCCESS_COUNT=0
ERROR_COUNT=0

echo "🚀 테스트 시작..."
echo ""

# 1. 헬스체크 (제외됨 - 확인용)
echo "1️⃣ Health Check (10회):"
for i in $(seq 1 10); do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$API_BASE_URL/api/ai/health")
  if [ "$HTTP_CODE" = "200" ]; then
    ((SUCCESS_COUNT++))
  else
    ((ERROR_COUNT++))
  fi
  printf "."
done
echo " ✅ 완료"
echo ""

# 2. 멘토 추천 API (메트릭 수집 대상)
echo "2️⃣ 멘토 추천 API (${NUM_REQUESTS}회):"
for i in $(seq 1 $NUM_REQUESTS); do
  # 랜덤 user_id (1-1000)
  USER_ID=$((RANDOM % 1000 + 1))
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    "$API_BASE_URL/api/ai/mentors/recommend/$USER_ID?top_k=5" 2>/dev/null)
  
  if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "404" ]; then
    ((SUCCESS_COUNT++))
  else
    ((ERROR_COUNT++))
  fi
  
  # 진행 표시
  if [ $((i % 10)) -eq 0 ]; then
    printf "$i "
  fi
  
  # API 과부하 방지
  sleep 0.05
done
echo " ✅ 완료"
echo ""

# 3. 이력서 파싱 API (메트릭 수집 대상) - 422 에러 예상
echo "3️⃣ 이력서 파싱 API (50회) - 422 에러 예상:"
for i in $(seq 1 50); do
  # 랜덤 task_id
  TASK_ID=$((RANDOM % 10000 + 1))
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$API_BASE_URL/api/ai/resumes/$TASK_ID/parse" \
    -H "Content-Type: application/json" \
    -d '{"s3_url": "https://example.com/test.pdf"}' 2>/dev/null)
  
  # 422는 validation error - 정상적인 응답
  if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "422" ] || [ "$HTTP_CODE" = "400" ]; then
    ((SUCCESS_COUNT++))
  else
    ((ERROR_COUNT++))
  fi
  
  if [ $((i % 10)) -eq 0 ]; then
    printf "$i "
  fi
  
  sleep 0.05
done
echo " ✅ 완료"
echo ""

# 4. 채용공고 파싱 API (메트릭 수집 대상)
echo "4️⃣ 채용공고 파싱 API (50회):"
for i in $(seq 1 50); do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$API_BASE_URL/api/ai/jobs/parse" \
    -H "Content-Type: application/json" \
    -d '{"url": "https://example.com/job/1234"}' 2>/dev/null)
  
  if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "422" ] || [ "$HTTP_CODE" = "400" ]; then
    ((SUCCESS_COUNT++))
  else
    ((ERROR_COUNT++))
  fi
  
  if [ $((i % 10)) -eq 0 ]; then
    printf "$i "
  fi
  
  sleep 0.05
done
echo " ✅ 완료"
echo ""

echo "============================================"
echo "테스트 완료!"
echo "============================================"
echo ""
echo "📊 결과:"
echo "  - 성공: $SUCCESS_COUNT"
echo "  - 실패: $ERROR_COUNT"
echo "  - 총 요청: $((SUCCESS_COUNT + ERROR_COUNT))"
echo ""
echo "⏳ CloudWatch 메트릭 확인:"
echo "  - 1-2분 후 CloudWatch Console에서 확인 가능"
echo "  - Namespace: ReFit/AI"
echo "  - Metrics: ResponseTime, RequestCount"
echo ""
echo "🔗 CloudWatch Console:"
echo "  https://ap-northeast-2.console.aws.amazon.com/cloudwatch/home?region=ap-northeast-2#metricsV2:graph=~();namespace=ReFit/AI"
