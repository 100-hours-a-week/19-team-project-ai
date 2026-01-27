# Re-Fit AI 운영 Runbooks

이 디렉토리는 Re-Fit AI 서비스의 운영 및 장애 대응 문서를 포함합니다.

## 📚 문서 목록

### 🔄 [롤백 Runbook](./rollback-ai-service.md)
- **목적**: AI 서비스 장애 발생 시 신속한 롤백 가이드
- **대상**: DevOps 팀, Backend 개발자
- **포함 내용**:
  - 장애 심각도 분류 (P0/P1/P2)
  - 장애 감지 및 판단 기준
  - 심각도별 롤백 프로세스
  - 롤백 후 검증 체크리스트
  - 트러블슈팅 가이드

## 🔔 장애 알림 시스템

### Discord 알림 채널
- **#ai-service-alerts**: 자동 알림 (CI/CD, 배포, 장애)
- **#incident-response**: 수동 보고 및 대응

### 알림 레벨

#### CI 알림
| 단계 | 성공 | 실패 |
|------|------|------|
| Lint & Test | - | 🟡 P1 |
| Integration | - | 🟡 P1 |
| Release Build | ✅ 아티팩트 생성 완료 | 🔴 P1 빌드 실패 |

#### CD 알림
| 이벤트 | 알림 |
|--------|------|
| 배포 시작 | 🚀 배포 시작 |
| 배포 성공 | ✅ 배포 완료 |
| 배포 실패 | 🚨 P0 배포 실패 |
| 헬스체크 실패 | 🚨 P0 헬스체크 실패 → 자동 롤백 시작 |
| 롤백 성공 | ✅ 롤백 완료 |
| 롤백 실패 | 🚨 P0 롤백 실패 (수동 개입 필요) |

### 심각도 정의

#### 🔴 P0 (Critical)
- **조건**: 전체 서비스 중단, 헬스체크 실패, 5xx > 50%
- **대응 시간**: 즉시 (5분 이내)
- **조치**: 즉시 롤백
- **알림**: Discord + @devops-oncall 멘션

#### 🟡 P1 (High)
- **조건**: 응답률 < 50%, 5xx 10-50%, CI 빌드 실패
- **대응 시간**: 15분 이내
- **조치**: 원인 파악 후 롤백 또는 Hot Fix
- **알림**: Discord

#### 🟢 P2 (Medium)
- **조건**: 응답 시간 증가, 간헐적 오류, 5xx 3-10%
- **대응 시간**: 1시간 이내
- **조치**: 모니터링 후 필요 시 롤백
- **알림**: Discord

## 🚀 CI/CD 파이프라인

### CI 워크플로우 (`.github/workflows/ci.yml`)
```
PR/Push → Lint & Test → Integration → Release
          ↓             ↓              ↓
       Discord       Discord       Discord + CD 트리거
```

### CD 워크플로우 (`.github/workflows/cd.yml`)
```
CD 시작 → 배포 → 헬스체크 → 성공/실패
  ↓        ↓        ↓          ↓
Discord  (배포)  (실패 시)  Discord
                  P0 알림
                    ↓
                 자동 롤백
                    ↓
              롤백 성공/실패
                    ↓
                 Discord
```

## 📋 빠른 참조

### 장애 대응 플로우

1. **Discord 알림 수신**
   - 심각도 확인 (P0/P1/P2)
   - 알림 내용 분석

2. **장애 확인**
   ```bash
   # 서버 접속
   ssh ec2-user@your-server-ip
   
   # 헬스체크
   curl http://localhost:8080/actuator/health
   
   # PM2 상태
   pm2 status
   
   # 로그 확인
   tail -n 50 /var/log/app/application.log | grep ERROR
   ```

3. **롤백 결정**
   - P0: 즉시 롤백
   - P1: 원인 파악 후 판단
   - P2: 모니터링 지속

4. **롤백 실행**
   ```bash
   # Runbook 참조
   # docs/runbooks/rollback-ai-service.md
   ```

5. **사후 처리**
   - 인시던트 보고서 작성
   - 원인 분석
   - 재발 방지 대책

## 🔧 서버 스크립트

### 롤백 스크립트 (서버 배포 필요)
서버에 다음 스크립트를 배포해야 합니다:
- `/opt/scripts/rollback.sh` - 수동 롤백 실행 스크립트
- `/opt/scripts/discord-notify.sh` - Discord 알림 전송 스크립트

**주의**: 이 스크립트들은 별도로 서버에 배포되어야 하며, Git 저장소에는 템플릿만 포함됩니다.

## 📞 긴급 연락망

| 역할 | Discord | 용도 |
|------|---------|------|
| 1차 대응 (DevOps) | @devops-oncall | P0/P1 장애 대응 |
| 2차 대응 (AI Backend) | @ai-backend-lead | 기술 지원 |
| 최종 에스컬레이션 | @cto | 30분 내 미해결 시 |

## 🔄 문서 업데이트

- **변경 이력**: Git commit 로그 참조
- **리뷰 주기**: 월 1회
- **개선 제안**: `#ai-service-alerts` 채널에 피드백

## 📚 관련 문서

- [롤백 Runbook](./rollback-ai-service.md)
- [CI 워크플로우](../../.github/workflows/ci.yml)
- [CD 워크플로우](../../.github/workflows/cd.yml)
- [프로젝트 README](../../README.md)
