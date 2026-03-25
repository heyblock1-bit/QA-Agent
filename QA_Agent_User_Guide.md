# QA Agent 사용 가이드

> **QA Agent**는 Google Sheets TC 시트를 5분마다 모니터링하면서, Fail이 기록된 TC를 자동으로 Jira 버그 티켓으로 생성하고 상태를 동기화하는 자동화 도구입니다.

---

## 전체 플로우 한눈에 보기

```
스프린트 시작
    │
    ▼
[1] config.md 업데이트
    (feature명, 버전, 담당자, 환경 등)
    │
    ▼
[2] sprint_setup.py 실행
    → Jira에 Epic 4개 자동 생성 (iOS / Android / Web / BE)
    → config.md에 Epic 키 자동 기입
    │
    ▼
[3] QA 팀이 Google Sheets TC 시트에 테스트 결과 기록
    (Pass / Fail / N/A / Pending / Blocked + Actual Result 입력)
    │
    ▼
[4] agent.py 실행 (상시 polling)
    → Fail + Actual Result 있는 row 감지
    → Jira 버그 티켓 자동 생성 + /qa-auto-gen 코멘트 추가
    → 시트 Ticket 컬럼에 티켓 ID 기입
    → TC 내용 변경 시 티켓 자동 업데이트
    → Pass로 변경 시 티켓 자동 Closed 전환
    → 스크린샷 폴더 자동 생성
    │
    ▼
[5] (선택) 스크린샷 첨부
    → screenshots/{platform}/{티켓키}/ 폴더에 파일 넣기
    → 다음 polling 사이클에서 자동 첨부 후 삭제
    │
    ▼
[6] report.py 실행 (필요 시)
    → TC 커버리지 리포트 출력 + KOR/EN MD 파일 자동 저장
    → --slack 옵션으로 Slack 붙여넣기용 텍스트 생성
```

---

## Step 1 — config.md 업데이트

스프린트가 시작되면 **가장 먼저** `config.md`를 수정합니다.
`agent.py`는 5분 polling마다 이 파일을 새로 읽으므로, 수정 후 재시작 없이 즉시 반영됩니다.

### 수정해야 할 항목

```markdown
## Sprint
# sprint은 자동 계산 (KST 기준 현재 주차) → 수정 불필요

# Jira 필드
server_env: Luke           # 서버 환경 (Luke / Dawn / 등)
release_version: 3.13.1    # 이번 스프린트 릴리즈 버전
bug_type: New Feature      # 이슈 카테고리 (New Feature / Bug 등)
reproducibility: Always    # 재현 빈도
test_type: Feature         # 테스트 타입

# 티켓 제목에 사용되는 값
squad_name: CoreUX                  # 스쿼드명 → 티켓 제목에 [CoreUX] 형태로 삽입
feature_name: TP/SL Revamp Phase 2  # 피처명 → 티켓 제목에 삽입
squad_env: squad-tpsl               # Steps to Produce의 env 값

## Test Account          ← Precondition에 계정 정보 없을 때 기본값으로 사용
test_account_id: jiseon+t1@prex.io
test_account_pwd: Swtest1!

## Assignee (Jira accountId) — 담당자 변경 시 수정
assignee_ios: 712020:...
assignee_aos: 633408...
assignee_web: 712020:...
assignee_be: 63a564...

## Epic — sprint_setup.py 실행 후 자동 기입되므로 수동 수정 불필요
epic_ios: QA-XXXXX
epic_aos: QA-XXXXX
epic_web: QA-XXXXX
epic_be: QA-XXXXX

## Android
aos_version: 3.13.101.tpsl-phase2
device_model_aos: Galaxy S25
os_version_aos: 16

## iOS
ios_version: 3.12.100 (9168)
device_model_ios: iPhone 16
os_version_ios: 26
```

### 생성되는 티켓 제목 예시

```
[W12][iOS][CoreUX][TP/SL Revamp Phase 2] 특정 조건에서 SL 설정 미저장
```

> **참고:** Sprint 주차(`W12`)는 KST 기준 현재 날짜의 ISO 주차로 자동 계산됩니다.
> TC 제목에 이미 `[xxx]` prefix가 있으면 자동으로 제거하고 위 형식으로 재구성합니다.

---

## Step 2 — Epic 생성 (sprint_setup.py)

새 스프린트 시작 시 **딱 한 번** 실행합니다.

```bash
python sprint_setup.py
```

### 동작 내용

- iOS / Android / Web / BE 4개 플랫폼에 Epic을 자동 생성
- Epic 제목 형식: `[W12][iOS][CoreUX] TP/SL Revamp Phase 2`
- 생성된 Epic 키를 `config.md`의 `epic_ios` / `epic_aos` / `epic_web` / `epic_be` 항목에 자동으로 덮어씀

### 실행 결과 예시

```
🚀 Sprint Setup - W12 / TP/SL Revamp Phase 2
==================================================
  ✅ Epic 생성: QA-19844 [iOS] [W12][iOS][CoreUX] TP/SL Revamp Phase 2
  ✅ Epic 생성: QA-19845 [Android] [W12][Android][CoreUX] TP/SL Revamp Phase 2
  ✅ Epic 생성: QA-19846 [Web] [W12][Web][CoreUX] TP/SL Revamp Phase 2
  ✅ Epic 생성: QA-19847 [BE] [W12][BE][CoreUX] TP/SL Revamp Phase 2

✅ config.md에 Epic 키 자동 업데이트 완료
==================================================
```

---

## Step 3 — Google Sheets TC 시트 작성

TC 시트의 컬럼 구조는 다음과 같습니다.

| 컬럼 | 내용 |
|------|------|
| A | Domain |
| B | Section |
| C | Component |
| D | Feature |
| **E** | **Title (TC 제목)** |
| F | Precondition |
| G | Procedure (Steps) |
| H | Expected Result |
| I | Priority (P1~P4) |
| **J** | **iOS 결과** (Pass / Fail / N/A / Pending / Blocked) |
| K | iOS Actual Result |
| **L** | iOS Ticket (자동 기입) |
| **M** | **AOS 결과** (Pass / Fail / N/A / Pending / Blocked) |
| N | AOS Actual Result |
| **O** | AOS Ticket (자동 기입) |
| **P** | **Web 결과** (Pass / Fail / N/A / Pending / Blocked) |
| Q | Web Actual Result |
| **R** | Web Ticket (자동 기입) |
| **S** | BE Actual Result |
| **T** | BE Ticket (자동 기입) |

### 티켓 자동 생성 트리거 조건

| 플랫폼 | 조건 |
|--------|------|
| iOS | J열 = `Fail` **AND** K열에 Actual Result 입력 |
| Android | M열 = `Fail` **AND** N열에 Actual Result 입력 |
| Web | P열 = `Fail` **AND** Q열에 Actual Result 입력 |
| BE | J+M+P열 **모두** `Fail` **AND** S열에 BE Actual Result 입력 |

> **주의:** Actual Result가 비어 있으면 티켓이 생성되지 않습니다.

### Pass 입력 시 티켓 자동 Close

이미 티켓이 생성된 TC의 결과를 `Pass`로 변경하면, 해당 Jira 티켓이 **자동으로 Closed** 상태로 전환됩니다.
단, 티켓 상태가 `Not Issue`인 경우 Closed 전환에서 제외됩니다.

---

## Step 4 — Agent 실행 (agent.py)

```bash
python agent.py
```

### 동작 방식

- **5분마다** 영문 시트 + KOR 시트 **두 시트 동시** 스캔
- 트리거 조건 충족 → Jira 버그 티켓 생성
- 생성된 티켓 ID를 시트 Ticket 컬럼에 자동 기입 (예: `QA-19900 (Ready)`)
- 티켓 생성 직후 Jira 코멘트에 `/qa-auto-gen` 자동 추가 (자동 생성 표시)
- 이미 티켓이 있는 row는 **업데이트 모드**: 시트 내용과 다른 필드만 자동 수정
- `Pass` 입력 시 해당 티켓 자동 Closed 전환 (Not Issue 제외)
- 티켓 상태가 변경되면 시트의 셀 값도 자동 갱신 (예: `QA-19900 (In Progress)`)

### 자동 생성 티켓 필드 매핑

| Jira 필드 | 출처 |
|-----------|------|
| Summary | `[sprint][platform][squad_name][feature_name] TC제목` |
| Priority | TC 시트 Priority 컬럼 (기본값: P3) |
| Platform | 해당 플랫폼 |
| Steps to Produce | env + test account + precondition + procedure |
| Actual Result | 시트 Actual Result 컬럼 |
| Expected Result | 시트 Expected 컬럼 |
| Client Version | config의 ios_version / aos_version |
| Device / OS | config의 device_model, os_version |
| Assignee | config의 assignee_ios / assignee_aos / assignee_web / assignee_be |
| Epic Link | config의 epic_ios / epic_aos / epic_web / epic_be |
| Server Env | config의 server_env |
| Release Version | config의 release_version |

**Steps to Produce 자동 구성 규칙:**
- `* env : {squad_env}`
- `* test account :` → TC Precondition에 `이메일/패스워드` 패턴이 있으면 자동 추출, 없으면 config의 test_account 사용
- `* precondition : {precondition}` (있는 경우)
- (빈 줄)
- `{procedure}` (Steps)

> **iOS 전용:** Summary, Actual Result, Expected Result, Precondition, Steps(Procedure)가 자동으로 **영어 번역**(DeepL)됩니다.

### 실행 결과 예시

```
🤖 QA Agent 시작 (5분마다 체크)
  📋 [TC_Sheet_EN] 체크 중...
  🌐 iOS 티켓 번역 중...
  ✅ 티켓 생성: QA-19900 [iOS] SL setting not saved under specific conditions
  📁 스크린샷 폴더 생성: screenshots/iOS/QA-19900/
  ✅ 티켓 생성: QA-19901 [Android] 특정 조건에서 SL 설정 미저장
  📁 스크린샷 폴더 생성: screenshots/Android/QA-19901/
  📋 [TC_Sheet_KOR] 체크 중...
  ✏️  티켓 업데이트: QA-19901 [Android] (customfield_10207)
  🔄 상태 변경: QA-19900 (In Progress)
✓ 2개 티켓 생성 완료
```

---

## Step 5 — 스크린샷 첨부 (선택)

티켓 생성 후 `screenshots/` 폴더에 스크린샷을 넣어두면, **다음 polling 사이클(최대 5분 이내)**에 자동으로 Jira 티켓에 첨부됩니다.

### 폴더 경로 규칙

```
screenshots/
├── iOS/
│   └── QA-19900/      ← 이 폴더에 파일 넣기
│       └── bug_screenshot.png
├── Android/
│   └── QA-19901/
├── Web/
│   └── QA-19902/
└── BE/
    └── QA-19903/
```

### 지원 파일 형식

`.png` `.jpg` `.jpeg` `.gif` `.webp` `.mov` `.mp4`

> 첨부 성공 후 로컬 파일은 자동으로 삭제됩니다.

---

## Step 6 — 커버리지 리포트 (report.py)

스프린트 중간이나 마무리 시점에 실행합니다. KOR 시트(`SHEET_NAME_KOR`) 기준으로 집계합니다.

### 기본 실행 (터미널 출력 + MD 파일 저장)

```bash
python report.py
```

터미널에 현황을 출력하고, 동시에 두 파일을 자동 저장합니다.

- `report_YYYYMMDD.md` — 한국어 마크다운
- `report_YYYYMMDD_en.md` — 영어 마크다운

### Slack 모드 (붙여넣기용 텍스트)

```bash
python report.py --slack
```

Slack 채널에 바로 붙여넣을 수 있는 포맷으로 출력합니다 (영어, 버그 건수만 표시).

### 집계 항목

| 항목 | 설명 |
|------|------|
| ✅ Pass | 통과 |
| ❌ Fail | 실패 |
| ➖ N/A | 해당 없음 |
| 🕐 Pending | 테스트 대기 |
| 🚫 Blocked | 블로커로 인한 중단 |
| ⬜ 미완료 | 위 항목 외 (빈 값 포함) |
| 📝 Total | 전체 TC 수 |

### 출력 예시 (터미널)

```
📊 TC Coverage Report
📋 Sheet: TC_Sheet_KOR | Sprint: W12
==================================================

[iOS]
  ✅ Pass    : 38 (76%)
  ❌ Fail    : 5 (10%)
  ➖ N/A     : 2 (4%)
  🕐 Pending : 3 (6%)
  🚫 Blocked : 0 (0%)
  ⬜ 미완료  : 2 (4%)
  📝 Total   : 50
  🐛 등록된 버그 (5건):
     QA-19900 (In Progress)
       └ [W12][iOS][CoreUX][TP/SL Revamp Phase 2] SL setting not saved...
...
==================================================

📄 KOR MD 저장 완료: report_20260323.md
📄 EN  MD 저장 완료: report_20260323_en.md
```

### 출력 예시 (--slack 모드)

```
TC Coverage Report | W12 | 2026-03-23 18:50 KST
Sheet: TC_Sheet_KOR

[ iOS ]  Total: 50
• Pass: 38 (76%)
• Fail: 5 (10%)
• N/A: 2 (4%)
• Pending: 3 (6%)
• Blocked: 0 (0%)
• Incomplete: 2 (4%)
• Bugs: 5
```

---

## 자주 묻는 것들

**Q. 스프린트 주차는 어떻게 계산되나요?**
KST(한국 시간) 기준으로 현재 날짜의 ISO 주차를 자동 계산합니다. `W12`처럼 표시됩니다. config.md를 수정할 필요 없습니다.

**Q. config.md를 수정하면 agent 재시작이 필요한가요?**
필요 없습니다. agent.py는 5분 polling 사이클마다 config.md를 새로 읽습니다.

**Q. iOS 티켓에만 영어가 들어가는 이유가 뭔가요?**
iOS 담당자가 영어권 팀원이기 때문에 DeepL API로 자동 번역됩니다. Android, Web, BE는 한국어 그대로 생성됩니다.

**Q. BE 티켓은 언제 생성되나요?**
iOS, Android, Web 세 플랫폼 모두 Fail이고, BE Actual Result(S열)에 내용이 입력됐을 때 생성됩니다.

**Q. 이미 있는 티켓의 내용이 바뀌면 어떻게 되나요?**
agent.py가 시트와 Jira 내용을 비교해서 다른 필드(Summary, Priority, Steps to Produce, Actual Result, Expected Result)만 자동으로 업데이트합니다.

**Q. 티켓 상태(Ready, In Progress 등)는 어디서 오나요?**
Jira에서 직접 조회해서 시트 Ticket 컬럼에 `QA-19900 (In Progress)` 형태로 자동 반영됩니다.

**Q. Pass로 바꾸면 티켓이 자동으로 닫히나요?**
네. 결과 컬럼에 Pass를 입력하면 Jira 티켓이 Closed로 자동 전환됩니다. 단, 티켓 상태가 `Not Issue`인 경우는 전환하지 않습니다.

**Q. /qa-auto-gen 코멘트는 뭔가요?**
agent.py가 자동으로 생성한 티켓임을 표시하는 코멘트입니다. 티켓 생성 직후 Jira에 자동으로 추가됩니다.

**Q. 영문 시트와 KOR 시트 둘 다 처리하나요?**
네. agent.py는 `.env`에 설정된 `SHEET_NAME`(영문)과 `SHEET_NAME_KOR`(KOR) 두 시트를 동시에 처리합니다. report.py는 KOR 시트 기준으로 집계합니다.
