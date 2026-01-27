#!/usr/bin/env python3
"""
requirements.txt → pyproject.toml 자동 동기화 스크립트
팀원이 requirements.txt를 업데이트하면 pyproject.toml도 자동 업데이트
"""

import re
import sys
from pathlib import Path


def parse_requirements(req_file: Path) -> list[str]:
    """requirements.txt에서 패키지 목록 추출"""
    if not req_file.exists():
        return []
    
    packages = []
    with open(req_file) as f:
        for line in f:
            line = line.strip()
            # 주석, 빈 줄, git URL 제외
            if not line or line.startswith('#') or line.startswith('git+'):
                continue
            
            # 버전 정보 정리 (==, >=, ~= 등)
            if '==' in line:
                pkg = line.split('==')[0].strip()
                version = line.split('==')[1].split(';')[0].strip()
                packages.append(f'    "{pkg}>={version}",')
            elif '>=' in line:
                packages.append(f'    "{line.split(";")[0].strip()}",')
            elif '<' in line or '~=' in line:
                pkg = re.split(r'[<~=]+', line)[0].strip()
                packages.append(f'    "{pkg}",')
            else:
                packages.append(f'    "{line.split(";")[0].strip()}",')
    
    return sorted(set(packages))


def parse_pyproject_dependencies(pyproject_file: Path) -> list[str]:
    """pyproject.toml에서 현재 dependencies 추출"""
    if not pyproject_file.exists():
        return []
    
    with open(pyproject_file) as f:
        content = f.read()
    
    # dependencies 배열 찾기
    pattern = r'dependencies\s*=\s*\[(.*?)\]'
    match = re.search(pattern, content, re.DOTALL)
    
    if not match:
        return []
    
    deps_block = match.group(1)
    deps = []
    for line in deps_block.split('\n'):
        line = line.strip()
        if line.startswith('"') and line.endswith((',', ',')):
            deps.append(line.rstrip(',').strip())
    
    return deps


def update_pyproject_toml(pyproject_file: Path, new_packages: list[str]) -> bool:
    """pyproject.toml의 dependencies 업데이트"""
    if not pyproject_file.exists():
        print(f"❌ {pyproject_file} 파일을 찾을 수 없습니다.")
        return False
    
    with open(pyproject_file) as f:
        content = f.read()
    
    # dependencies 배열 찾기
    pattern = r'(dependencies\s*=\s*\[)(.*?)(\])'
    match = re.search(pattern, content, re.DOTALL)
    
    if not match:
        print("❌ pyproject.toml에서 dependencies 섹션을 찾을 수 없습니다.")
        return False
    
    # 새 dependencies 생성
    new_deps_str = '\n' + '\n'.join(new_packages) + '\n'
    new_content = content[:match.start(2)] + new_deps_str + content[match.end(2):]
    
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
    req_set = set(req_packages)
    pyproject_set = set(pyproject_packages)
    
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
    
    # pyproject.toml 업데이트 (requirements.txt 우선)
    print(f"\n🔄 pyproject.toml 업데이트 중...")
    
    # requirements.txt의 모든 패키지 사용
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
