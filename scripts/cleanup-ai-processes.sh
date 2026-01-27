#!/bin/bash
# AI 서비스 프로세스 완전 정리 및 재시작 스크립트

set -e

echo "======================================"
echo "AI 서비스 프로세스 정리 시작"
echo "======================================"

# 1. 현재 상태 확인
echo ""
echo "[1/5] 현재 PM2 프로세스 상태:"
pm2 list

echo ""
echo "[2/5] 8000번 포트 사용 현황:"
sudo lsof -i :8000 || echo "포트 사용 중인 프로세스 없음"

# 2. 모든 AI 관련 프로세스 정리
echo ""
echo "[3/5] 모든 AI 관련 PM2 프로세스 정리 중..."
pm2 list | grep -E 'ai-service|ai-serv' | awk '{print $2}' | while read -r process_name; do
  if [ -n "$process_name" ] && [ "$process_name" != "name" ]; then
    echo "  - 프로세스 정리: $process_name"
    pm2 stop "$process_name" 2>/dev/null || true
    pm2 delete "$process_name" 2>/dev/null || true
  fi
done

# 3. 8000번 포트 강제 해제
echo ""
echo "[4/5] 8000번 포트 강제 해제..."
sudo lsof -ti:8000 | xargs -r sudo kill -9 2>/dev/null || echo "  포트 이미 해제됨"
sleep 2

# 4. AI 서비스만 깨끗하게 재시작
echo ""
echo "[5/5] AI 서비스 재시작..."
pm2 start /home/ubuntu/refit/infra/pm2/ecosystem.ai.config.js --only ai-service --env production

echo ""
echo "======================================"
echo "AI 서비스 정리 완료!"
echo "======================================"

# 5. 최종 상태 확인
echo ""
echo "최종 PM2 상태:"
pm2 list

echo ""
echo "최근 로그 (10줄):"
pm2 logs ai-service --lines 10 --nostream

echo ""
echo "✅ 스크립트 실행 완료"
echo "ℹ️  실시간 로그 확인: pm2 logs ai-service"
