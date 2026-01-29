#!/usr/bin/env python3
"""
requirements.txt → pyproject.toml 자동 동기화 스크립트
팀원이 requirements.txt를 업데이트하면 pyproject.toml도 자동 업데이트
"""

import re
import sys
from pathlib import Path


def _package_key(spec: str) -> str:
    """
    dependency spec에서 비교용 패키지 키 추출.
    예) "uvicorn[standard]>=0.27.0" -> "uvicorn"
    """
    m = re.match(r"^[A-Za-z0-9_.-]+", spec.strip())
    return (m.group(0) if m else spec.strip()).lower()


def parse_requirements(req_file: Path) -> list[str]:
    """requirements.txt에서 dependency spec 목록 추출 (원문 spec 유지)"""
    if not req_file.exists():
        return []
    
    specs: list[str] = []
    with open(req_file) as f:
        for line in f:
            line = line.strip()
            # 주석, 빈 줄, git URL 제외
            if not line or line.startswith('#') or line.startswith('git+'):
                continue
            
            # 환경 마커(;)는 제거하고 spec만 사용
            spec = line.split(";")[0].strip()
            specs.append(spec)
    
    # 안정적인 결과를 위해 키 기준으로 중복 제거(첫 등장 우선)
    seen: set[str] = set()
    deduped: list[str] = []
    for spec in specs:
        key = _package_key(spec)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(spec)
    return deduped


def parse_pyproject_dependencies(pyproject_file: Path) -> list[str]:
    """pyproject.toml에서 현재 dependencies 추출"""
    if not pyproject_file.exists():
        return []
    
    with open(pyproject_file) as f:
        content = f.read()

    # dependencies 배열 찾기 (extras의 ']'에 걸리지 않도록 닫는 ']'는 라인 시작으로 제한)
    pattern = r"(?ms)^[ \t]*dependencies\s*=\s*\[\s*\n(.*?)(^[ \t]*\]\s*\n)"
    match = re.search(pattern, content)
    if not match:
        return []

    deps_block = match.group(1)
    deps: list[str] = []
    for line in deps_block.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r'^"([^"]+)"\s*,?\s*$', s)
        if m:
            deps.append(m.group(1))
    return deps


def update_pyproject_toml(pyproject_file: Path, new_packages: list[str]) -> bool:
    """
    pyproject.toml의 dependencies 업데이트.
    - requirements.txt에만 있는 패키지만 추가(기존 라인/주석 최대 보존)
    - extras(예: uvicorn[standard]) 때문에 ']'를 잘못 매칭하지 않도록,
      dependencies 닫는 ']'는 **라인 시작** 기준으로 찾는다.
    """
    if not pyproject_file.exists():
        print(f"❌ {pyproject_file} 파일을 찾을 수 없습니다.")
        return False
    
    with open(pyproject_file) as f:
        content = f.read()
    
    # dependencies 배열 찾기 (닫는 괄호는 라인 시작의 ']'만 인정)
    pattern = r"(?ms)(^[ \t]*dependencies\s*=\s*\[\s*\n)(.*?)(^[ \t]*\]\s*\n)"
    match = re.search(pattern, content)
    if not match:
        print("❌ pyproject.toml에서 dependencies 섹션을 찾을 수 없습니다.")
        return False

    prefix, block, suffix = match.group(1), match.group(2), match.group(3)

    # 기존 dependency spec 추출(주석/빈줄 제외, 따옴표 제거)
    existing_specs: list[str] = []
    for line in block.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith('"'):
            # "spec", 형태만 고려
            m = re.match(r'^"([^"]+)"\s*,?\s*$', s)
            if m:
                existing_specs.append(m.group(1))

    existing_keys = {_package_key(s) for s in existing_specs}
    req_keys = {_package_key(s) for s in new_packages}

    missing_keys = sorted(req_keys - existing_keys)
    if not missing_keys:
        print("✅ pyproject.toml에 추가할 패키지가 없습니다.")
        return True

    # requirements spec 중 missing만 골라 추가(원문 spec 유지)
    missing_specs: list[str] = []
    for spec in new_packages:
        if _package_key(spec) in missing_keys:
            missing_specs.append(spec)

    insertion = ""
    for spec in missing_specs:
        insertion += f'    "{spec}",\n'

    # block 끝에 추가 (기존 주석/정렬 최대 보존)
    if block and not block.endswith("\n"):
        block += "\n"
    new_block = block + insertion

    new_content = content[: match.start(2)] + new_block + content[match.end(2) :]
    
    # 파일 쓰기
    with open(pyproject_file, 'w') as f:
        f.write(new_content)
    
    return True


def main():
    """메인 실행 함수"""
    # 경로 설정
    base_dir = Path(__file__).parent.parent
    req_file = base_dir / "ai_app" / "requirements.txt"
    pyproject_file = base_dir / "pyproject.toml"
    
    print("=" * 50)
    print("requirements.txt → pyproject.toml 동기화")
    print("=" * 50)
    
    # requirements.txt 확인
    if not req_file.exists():
        print(f"✅ {req_file} 없음 - 스킵")
        return 0
    
    print(f"\n📦 requirements.txt 발견: {req_file}")
    
    # 패키지 목록 추출
    req_packages = parse_requirements(req_file)
    pyproject_packages = parse_pyproject_dependencies(pyproject_file)
    
    print(f"\n📋 Requirements.txt 패키지: {len(req_packages)}개")
    print(f"📋 Pyproject.toml 패키지: {len(pyproject_packages)}개")
    
    # 차이 확인
    req_set = {_package_key(s) for s in req_packages}
    pyproject_set = {_package_key(s) for s in pyproject_packages}
    
    missing = req_set - pyproject_set
    extra = pyproject_set - req_set
    
    if missing:
        print(f"\n⚠️  Requirements.txt에만 있는 패키지: {len(missing)}개")
        for pkg in sorted(missing):
            print(f"  + {pkg}")
    
    if extra:
        print(f"\n⚠️  Pyproject.toml에만 있는 패키지: {len(extra)}개")
        for pkg in sorted(extra):
            print(f"  - {pkg}")
    
    if not missing and not extra:
        print("\n✅ 이미 동기화되어 있습니다!")
        return 0
    
    # pyproject.toml 업데이트 (requirements.txt에만 있는 패키지만 추가)
    print(f"\n🔄 pyproject.toml 업데이트 중(추가만)...")

    if update_pyproject_toml(pyproject_file, req_packages):
        print(f"✅ pyproject.toml 업데이트 완료!")
        print(f"\n📝 다음 단계:")
        print(f"  git add pyproject.toml")
        print(f'  git commit -m "chore: requirements.txt와 pyproject.toml 동기화"')
        return 0
    else:
        print("❌ 업데이트 실패!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
