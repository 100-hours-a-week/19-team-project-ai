#!/bin/bash
# AI 서비스 헬스체크 스크립트

set -e

# 색상 정의
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "======================================"
echo "AI 서비스 헬스체크 시작"
echo "======================================"

# 1. 로컬 헬스체크 (서버 내부)
echo ""
echo "1️⃣  로컬 헬스체크 (localhost:8000)"
RESPONSE=$(curl -s -w "\n%{http_code}" http://localhost:8000/api/ai/health 2>/dev/null || echo "000")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" = "200" ]; then
    echo -e "   ${GREEN}✅ 성공${NC}"
    echo "   HTTP 상태: $HTTP_CODE"
    echo "   응답: $BODY"
else
    echo -e "   ${RED}❌ 실패${NC}"
    echo "   HTTP 상태: $HTTP_CODE"
    exit 1
fi

# 2. 외부 도메인 헬스체크 (선택사항)
# DOMAIN을 실제 도메인으로 변경하세요
# DOMAIN="your-domain.com"
# echo ""
# echo "2️⃣  외부 헬스체크 (https://$DOMAIN)"
# RESPONSE=$(curl -s -w "\n%{http_code}" https://$DOMAIN/api/ai/health 2>/dev/null || echo "000")
# HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
# BODY=$(echo "$RESPONSE" | head -n-1)
# 
# if [ "$HTTP_CODE" = "200" ]; then
#     echo -e "   ${GREEN}✅ 성공${NC}"
#     echo "   HTTP 상태: $HTTP_CODE"
#     echo "   응답: $BODY"
# else
#     echo -e "   ${RED}❌ 실패${NC}"
#     echo "   HTTP 상태: $HTTP_CODE"
# fi

# 3. PM2 상태 확인
echo ""
echo "3️⃣  PM2 프로세스 상태"
if pm2 describe ai-service > /dev/null 2>&1; then
    STATUS=$(pm2 jlist | jq -r '.[] | select(.name=="ai-service") | .pm2_env.status')
    UPTIME=$(pm2 jlist | jq -r '.[] | select(.name=="ai-service") | .pm2_env.pm_uptime' | xargs -I {} date -d @{} +"%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "N/A")
    CPU=$(pm2 jlist | jq -r '.[] | select(.name=="ai-service") | .monit.cpu')
    MEM=$(pm2 jlist | jq -r '.[] | select(.name=="ai-service") | .monit.memory' | awk '{printf "%.1fMB", $1/1024/1024}')
    
    if [ "$STATUS" = "online" ]; then
        echo -e "   ${GREEN}✅ Online${NC}"
        echo "   CPU: ${CPU}%"
        echo "   메모리: ${MEM}"
    else
        echo -e "   ${RED}❌ ${STATUS}${NC}"
    fi
else
    echo -e "   ${RED}❌ 프로세스를 찾을 수 없음${NC}"
    exit 1
fi

# 4. 포트 확인
echo ""
echo "4️⃣  8000번 포트 사용 현황"
PORT_CHECK=$(sudo lsof -i :8000 2>/dev/null | grep LISTEN || echo "")
if [ -n "$PORT_CHECK" ]; then
    echo -e "   ${GREEN}✅ 8000번 포트 사용 중${NC}"
    echo "$PORT_CHECK" | awk 'NR>1 {print "   프로세스:", $1, "PID:", $2}'
else
    echo -e "   ${RED}❌ 8000번 포트 사용 안 함${NC}"
    exit 1
fi

# 5. 최근 로그 확인
echo ""
echo "5️⃣  최근 에러 로그 (최근 5줄)"
if [ -f "/home/ubuntu/refit/logs/ai/error.log" ]; then
    ERRORS=$(tail -n 5 /home/ubuntu/refit/logs/ai/error.log 2>/dev/null | grep -i "error" || echo "")
    if [ -z "$ERRORS" ]; then
        echo -e "   ${GREEN}✅ 최근 에러 없음${NC}"
    else
        echo -e "   ${YELLOW}⚠️  최근 에러 발견:${NC}"
        echo "$ERRORS" | sed 's/^/   /'
    fi
else
    echo -e "   ${YELLOW}⚠️  로그 파일 없음${NC}"
fi

echo ""
echo "======================================"
echo -e "${GREEN}헬스체크 완료!${NC}"
echo "======================================"
