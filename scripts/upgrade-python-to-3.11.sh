#!/bin/bash
# EC2 서버 Python 3.11 업그레이드 및 venv 재생성 스크립트
# Ubuntu 22.04 LTS 기준

set -e

echo "======================================"
echo "Python 3.11 업그레이드 시작"
echo "======================================"

# 0. 현재 Python 버전 확인
echo ""
echo "[0/8] 현재 Python 버전:"
python3 --version
which python3

# 1. 패키지 목록 업데이트
echo ""
echo "[1/8] 패키지 목록 업데이트..."
sudo apt update

# 2. Python 3.11 설치
echo ""
echo "[2/8] Python 3.11 설치..."
sudo apt install -y python3.11 python3.11-venv python3.11-dev

# 3. Python 3.11 버전 확인
echo ""
echo "[3/8] 설치된 Python 3.11 버전 확인:"
python3.11 --version

# 4. AI 서비스 중지 (안전한 재생성을 위해)
echo ""
echo "[4/8] AI 서비스 중지..."
pm2 stop ai-service 2>/dev/null || echo "  서비스가 실행 중이 아님"

# 5. 기존 venv 백업
echo ""
echo "[5/8] 기존 venv 백업..."
if [ -d "/home/ubuntu/refit/app/ai/venv" ]; then
    BACKUP_NAME="venv_backup_$(date +%Y%m%d_%H%M%S)"
    sudo mv /home/ubuntu/refit/app/ai/venv "/home/ubuntu/refit/app/ai/$BACKUP_NAME"
    echo "  백업 완료: $BACKUP_NAME"
else
    echo "  기존 venv 없음"
fi

# 6. Python 3.11 기반 새 venv 생성
echo ""
echo "[6/8] Python 3.11 기반 새 venv 생성..."
cd /home/ubuntu/refit/app/ai
python3.11 -m venv venv
echo "  venv 생성 완료"

# 7. venv에서 의존성 설치
echo ""
echo "[7/8] 의존성 설치 중..."
source venv/bin/activate

# pip 업그레이드
python -m pip install --upgrade pip

# wheel 패키지 설치 (빌드 성능 향상)
pip install wheel

# 프로젝트 의존성 설치
if [ -f "/home/ubuntu/refit/app/ai/ai_app/requirements.txt" ]; then
    echo "  requirements.txt에서 의존성 설치..."
    pip install -r /home/ubuntu/refit/app/ai/ai_app/requirements.txt
else
    echo "  ⚠️  requirements.txt 없음. pyproject.toml 확인 필요"
fi

# 8. 설치 확인
echo ""
echo "[8/8] 설치 확인..."
echo "  Python 버전: $(python --version)"
echo "  pip 버전: $(pip --version)"
echo "  uvicorn 설치: $(which uvicorn)"

deactivate

echo ""
echo "======================================"
echo "Python 3.11 업그레이드 완료!"
echo "======================================"

# 9. AI 서비스 재시작
echo ""
echo "AI 서비스 재시작..."
pm2 start /home/ubuntu/refit/infra/pm2/ecosystem.ai.config.js --only ai-service --env production

echo ""
echo "최종 상태:"
pm2 list

echo ""
echo "✅ 업그레이드 완료"
echo "ℹ️  로그 확인: pm2 logs ai-service"
echo "ℹ️  Python 버전 확인: source /home/ubuntu/refit/app/ai/venv/bin/activate && python --version"
