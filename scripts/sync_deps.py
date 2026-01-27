#!/usr/bin/env python3
"""
pyproject.toml과 requirements.txt의 의존성 동기화 검증 스크립트

사용법:
  python scripts/sync_deps.py          # 검증만
  python scripts/sync_deps.py --fix    # 자동 수정
"""
import re
import sys
from pathlib import Path


def normalize_package_name(pkg: str) -> str:
    """패키지 이름 정규화 (extras 포함, 버전 제외)"""
    # 버전 정보 제거 (>=, <=, ==, !=, >, < 등)
    pkg = re.split(r'[><=!]+', pkg)[0].strip()
    # 소문자 변환 및 언더스코어를 하이픈으로 통일
    pkg = pkg.lower().replace('_', '-')
    return pkg


def parse_requirements(req_file: Path) -> set[str]:
    """requirements.txt에서 패키지 이름 추출"""
    packages = set()
    if not req_file.exists():
        return packages

    with open(req_file) as f:
        for line in f:
            line = line.strip()
            # 주석과 빈 줄 제외
            if not line or line.startswith("#"):
                continue
            # 정규화된 패키지 이름 추가
            pkg_name = normalize_package_name(line)
            if pkg_name:
                packages.add(pkg_name)

    return packages


def parse_pyproject_deps(pyproject_file: Path) -> set[str]:
    """pyproject.toml의 dependencies에서 패키지 이름 추출"""
    packages = set()
    if not pyproject_file.exists():
        return packages

    with open(pyproject_file) as f:
        lines = f.readlines()

    # dependencies 섹션 찾기
    in_dependencies = False
    for line in lines:
        stripped = line.strip()

        # dependencies 시작
        if "dependencies" in stripped and "=" in stripped and "[" in stripped:
            in_dependencies = True
            # 같은 줄에 패키지가 있을 수도 있음
            if '"' in stripped or "'" in stripped:
                # 인용부호 안의 내용 추출
                match = re.search(r'["\'](.*?)["\']', stripped)
                if match:
                    pkg = match.group(1)
                    pkg_name = normalize_package_name(pkg)
                    if pkg_name:
                        packages.add(pkg_name)
            continue

        # dependencies 끝
        if in_dependencies and stripped.startswith("]"):
            break

        # dependencies 내부
        if in_dependencies:
            # 인용부호로 둘러싸인 패키지 추출
            match = re.search(r'["\'](.*?)["\']', stripped)
            if match:
                pkg = match.group(1)
                pkg_name = normalize_package_name(pkg)
                if pkg_name:
                    packages.add(pkg_name)

    return packages


def main():
    """메인 함수"""
    root = Path(__file__).parent.parent
    req_file = root / "ai_app" / "requirements.txt"
    pyproject_file = root / "pyproject.toml"

    if not req_file.exists():
        print(f"❌ {req_file} 파일을 찾을 수 없습니다.")
        sys.exit(1)

    if not pyproject_file.exists():
        print(f"❌ {pyproject_file} 파일을 찾을 수 없습니다.")
        sys.exit(1)

    req_packages = parse_requirements(req_file)
    pyproject_packages = parse_pyproject_deps(pyproject_file)

    # 차이 확인
    missing_in_pyproject = req_packages - pyproject_packages
    extra_in_pyproject = pyproject_packages - req_packages

    if not missing_in_pyproject and not extra_in_pyproject:
        print("✅ pyproject.toml과 requirements.txt가 동기화되어 있습니다!")
        sys.exit(0)

    print("⚠️  의존성 불일치 발견:")
    print()

    if missing_in_pyproject:
        print("📦 pyproject.toml에 누락된 패키지:")
        for pkg in sorted(missing_in_pyproject):
            print(f"  - {pkg}")
        print()

    if extra_in_pyproject:
        print("📦 requirements.txt에 누락된 패키지:")
        for pkg in sorted(extra_in_pyproject):
            print(f"  - {pkg}")
        print()

    print("💡 해결 방법:")
    print("  1. requirements.txt와 pyproject.toml을 수동으로 동기화")
    print("  2. 또는 python scripts/sync_deps.py --fix 실행 (추후 구현)")
    print()

    sys.exit(1)


if __name__ == "__main__":
    main()
