#!/bin/bash
# pyproject.toml에서 requirements.txt 자동 생성 스크립트

set -e

echo "======================================"
echo "requirements.txt 자동 생성"
echo "======================================"

# venv 활성화 확인
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  가상환경이 활성화되지 않았습니다."
    echo "다음 명령을 실행하세요:"
    echo "  source venv/bin/activate"
    exit 1
fi

# pyproject.toml 확인
if [ ! -f "pyproject.toml" ]; then
    echo "❌ pyproject.toml을 찾을 수 없습니다."
    exit 1
fi

echo ""
echo "1️⃣  현재 설치된 패키지 확인..."
pip list

echo ""
echo "2️⃣  requirements.txt 생성 중..."

# 프로덕션 의존성만 (dev 제외)
pip freeze | grep -v -E "pytest|ruff|mypy|bandit|build" > ai_app/requirements.txt

echo ""
echo "3️⃣  생성된 requirements.txt:"
cat ai_app/requirements.txt

echo ""
echo "======================================"
echo "✅ requirements.txt 생성 완료!"
echo "======================================"
echo ""
echo "📝 다음 단계:"
echo "  1. git add ai_app/requirements.txt"
echo "  2. git commit -m 'chore: requirements.txt 업데이트'"
echo "  3. git push"
