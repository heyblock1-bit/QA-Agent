# QA Agent

QA 테스트 자동화 에이전트. Google Sheets의 TC(Test Case) 실행 결과를 모니터링하고, Fail 항목에 대해 Jira 티켓을 자동 생성합니다.

## 프로젝트 구조

- `agent.py` — 메인 에이전트. Sheets 폴링 → Fail 감지 → Jira 티켓 생성 → 스크린샷 첨부
- `report.py` — TC 커버리지 리포트 생성 (플랫폼별 Pass/Fail 현황, 버그 목록)
- `sprint_setup.py` — 스프린트 초기 설정 (Jira Epic 생성, config.md 업데이트)
- `config.md` — 스프린트별 Jira 필드 설정 (릴리즈 버전, Epic 키, Assignee 등)
- `.env` — API 키, 시트 URL 등 민감 정보 (git 미추적)
- `screenshots/` — 플랫폼/티켓별 스크린샷 저장 폴더

## 실행

```bash
python agent.py          # 메인 에이전트 (5분 간격 폴링)
python report.py         # TC 리포트 생성
python report.py --slack # Slack용 텍스트 출력
python sprint_setup.py   # 새 스프린트 Epic 생성
```

## 외부 연동

- **Jira**: REST API v2 (티켓 생성/조회/전환, 스크린샷 첨부)
- **Google Sheets**: gspread (TC 시트 읽기/쓰기)
- **DeepL / Google Translate**: iOS 티켓 영문 번역
- **Prex MCP**: Jira, Notion, API 스펙 조회 가능

## 주의사항

- `.env`, `google-credentials.json`은 절대 수정/커밋하지 말 것
- `config.md` 수정 시 `key: value` 형식을 유지할 것 (인라인 주석 `#` 허용)
- 스프린트(`sprint`)는 KST 기준 현재 주차로 자동 계산됨
