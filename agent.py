import time
import re
import os
import requests
import base64
import gspread
import deepl
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

def get_current_sprint():
    kst = timezone(timedelta(hours=9))
    week = datetime.now(kst).isocalendar()[1]
    return f"w{week}"

load_dotenv()

# ─── 설정 ────────────────────────────────────────────────────────────────────

SPREADSHEET_URL = os.getenv("SPREADSHEET_URL")
SHEET_NAME = os.getenv("SHEET_NAME")
SHEET_NAME_KOR = os.getenv("SHEET_NAME_KOR")
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE")
CONFIG_FILE = os.getenv("CONFIG_FILE")

JIRA_URL = os.getenv("JIRA_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_TOKEN = os.getenv("JIRA_TOKEN")

POLL_INTERVAL = 300  # 5분
SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", os.path.join(os.path.dirname(__file__), "screenshots"))

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mov", ".mp4"}

# 컬럼 인덱스 (0-based)
COL_DOMAIN = 0
COL_SECTION = 1
COL_COMPONENT = 2
COL_FEATURE = 3
COL_TITLE = 4
COL_PRECONDITION = 5
COL_PROCEDURE = 6
COL_EXPECTED = 7
COL_PRIORITY = 8
COL_IOS = 9          # J
COL_IOS_ACTUAL = 10  # K
COL_IOS_TICKET = 11  # L
COL_AOS = 12         # M
COL_AOS_ACTUAL = 13  # N
COL_AOS_TICKET = 14  # O
COL_WEB = 15         # P
COL_WEB_ACTUAL = 16  # Q
COL_WEB_TICKET = 17  # R
COL_BE_ACTUAL  = 18  # S
COL_BE_TICKET  = 19  # T

# ─── config.md 파싱 ──────────────────────────────────────────────────────────

def load_config(path):
    config = {}
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, _, value = line.partition(":")
                value = value.split("#")[0].strip()  # 인라인 주석 제거
                config[key.strip()] = value
    return config

# ─── 번역 (iOS 전용) ─────────────────────────────────────────────────────────

def translate_to_english(text):
    if not text or not text.strip():
        return text
    # DeepL 쿼터 확인 후 소진 시 Google Translate 사용
    try:
        translator = deepl.Translator(os.getenv("DEEPL_API_KEY"))
        usage = translator.get_usage()
        if usage.character.count >= usage.character.limit:
            raise Exception("DeepL 쿼터 소진")
        result = translator.translate_text(text, target_lang="EN-US")
        return result.text
    except Exception:
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source='auto', target='en').translate(text)


# ─── Jira 이메일 → accountId 변환 캐시 ──────────────────────────────────────

_account_id_cache = {}

def get_account_id(email):
    if email in _account_id_cache:
        return _account_id_cache[email]
    r = requests.get(
        f"{JIRA_URL}/rest/api/2/user/search",
        headers=get_jira_headers(),
        params={"query": email},
        verify=False
    )
    users = r.json()
    if users:
        _account_id_cache[email] = users[0]["accountId"]
        return users[0]["accountId"]
    return None

# ─── Google Sheets ───────────────────────────────────────────────────────────

def get_sheets():
    creds = Credentials.from_service_account_file(
        CREDENTIALS_FILE,
        scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_url(SPREADSHEET_URL)
    sheets = [sh.worksheet(SHEET_NAME)]
    if SHEET_NAME_KOR:
        sheets.append(sh.worksheet(SHEET_NAME_KOR))
    return sheets

def create_screenshot_folder(platform, ticket_key):
    folder = os.path.join(SCREENSHOTS_DIR, platform, ticket_key)
    os.makedirs(folder, exist_ok=True)
    print(f"  📁 스크린샷 폴더 생성: screenshots/{platform}/{ticket_key}/")

def attach_screenshots(ticket_key, platform):
    folder = os.path.join(SCREENSHOTS_DIR, platform, ticket_key)
    if not os.path.isdir(folder):
        return
    images = [f for f in os.listdir(folder) if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS]
    if not images:
        return
    token = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_TOKEN}".encode()).decode()
    headers = {"Authorization": f"Basic {token}", "X-Atlassian-Token": "no-check"}
    all_success = True
    for filename in images:
        filepath = os.path.join(folder, filename)
        with open(filepath, "rb") as f:
            r = requests.post(
                f"{JIRA_URL}/rest/api/2/issue/{ticket_key}/attachments",
                headers=headers,
                files={"file": (filename, f)},
                verify=False
            )
        if r.status_code == 200:
            print(f"  📎 첨부 완료: {ticket_key} ← {filename}")
        else:
            print(f"  ❌ 첨부 실패 ({r.status_code}): {filename}")
            all_success = False
    if all_success:
        new_folder = folder + "(첨부됨)"
        os.rename(folder, new_folder)
        print(f"  📁 폴더 이름 변경: {ticket_key} → {ticket_key}(첨부됨)")

def write_ticket_id(sheet, row_index, col_index, ticket_id):
    # row_index: 0-based → gspread는 1-based이므로 +2 (헤더 row 포함)
    sheet.update_cell(row_index + 2, col_index + 1, ticket_id)

# ─── Jira ────────────────────────────────────────────────────────────────────

def get_ticket_status(ticket_key):
    r = requests.get(
        f"{JIRA_URL}/rest/api/2/issue/{ticket_key}?fields=status",
        headers=get_jira_headers(),
        verify=False
    )
    if r.status_code == 200:
        return r.json()["fields"]["status"]["name"]
    return None

def close_ticket(ticket_key):
    r = requests.post(
        f"{JIRA_URL}/rest/api/2/issue/{ticket_key}/transitions",
        headers=get_jira_headers(),
        json={"transition": {"id": "61"}},
        verify=False
    )
    if r.status_code == 204:
        print(f"  ✅ 티켓 Close: {ticket_key}")
    else:
        print(f"  ❌ Close 실패 ({r.status_code}): {r.text[:100]}")

def get_ticket_fields(ticket_key):
    r = requests.get(
        f"{JIRA_URL}/rest/api/2/issue/{ticket_key}?fields=summary,priority,customfield_10206,customfield_10207,customfield_10208",
        headers=get_jira_headers(),
        verify=False
    )
    if r.status_code == 200:
        return r.json()["fields"]
    return None

def update_jira_ticket(ticket_key, config, row, platform, actual_result="", eng_row=None):
    title = row[COL_TITLE]
    precondition = row[COL_PRECONDITION]
    procedure = row[COL_PROCEDURE]
    expected = row[COL_EXPECTED]
    priority = row[COL_PRIORITY] if row[COL_PRIORITY] else "P3"
    sprint = get_current_sprint()

    squad_name = config.get("squad_name", "")
    feature_name = config.get("feature_name", "")

    if platform == "Android":
        platform_label = "Android"
    elif platform == "iOS":
        platform_label = "iOS"
    elif platform == "Web":
        platform_label = "Web"
    else:
        platform_label = "BE"

    squad_env = config.get("squad_env", "")
    steps_lines = [f"* env : {squad_env}"]
    account_match = re.search(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]+\s*/\s*\S+', precondition)
    if account_match:
        steps_lines.append(f"* test account : {account_match.group().strip()}")
    else:
        test_id = config.get("test_account_id", "")
        test_pwd = config.get("test_account_pwd", "")
        if test_id and test_pwd:
            steps_lines.append(f"* test account : {test_id} / {test_pwd}")
        else:
            steps_lines.append(f"* test account : ")

    if platform == "iOS":
        if eng_row is not None:
            print("  📋 ENG 시트에서 iOS 컨텐츠 사용 중...")
            precondition_text = eng_row[COL_PRECONDITION] if len(eng_row) > COL_PRECONDITION else precondition
            procedure_text = eng_row[COL_PROCEDURE] if len(eng_row) > COL_PROCEDURE else procedure
            expected = eng_row[COL_EXPECTED] if len(eng_row) > COL_EXPECTED else expected
            eng_title = eng_row[COL_TITLE] if len(eng_row) > COL_TITLE else title
            clean_title = re.sub(r'^(\[.*?\]\s*)+', '', eng_title).strip()
        else:
            print("  🌐 iOS 티켓 번역 중...")
            try:
                precondition_text = translate_to_english(precondition)
                procedure_text = translate_to_english(procedure)
                actual_result = translate_to_english(actual_result)
                expected = translate_to_english(expected)
            except Exception as e:
                print(f"  ⚠️ 번역 실패, 한국어로 업데이트: {e}")
                precondition_text = precondition
                procedure_text = procedure
            clean_title = re.sub(r'^(\[.*?\]\s*)+', '', title).strip()
            try:
                clean_title = translate_to_english(clean_title)
            except Exception:
                pass
    else:
        precondition_text = precondition
        procedure_text = procedure
        clean_title = re.sub(r'^(\[.*?\]\s*)+', '', title).strip()

    summary = f"[{sprint.upper()}][{platform_label}][{squad_name}][{feature_name}] {clean_title}"

    if precondition_text:
        steps_lines.append(f"* precondition : {precondition_text}")
    steps_lines.append("")
    if procedure_text:
        steps_lines.append(procedure_text)

    steps_to_produce = "\n".join(steps_lines)

    current = get_ticket_fields(ticket_key)
    if not current:
        return False

    updates = {}
    if current.get("summary", "") != summary:
        updates["summary"] = summary
    if current.get("priority", {}).get("name", "") != priority:
        updates["priority"] = {"name": priority}
    if current.get("customfield_10206", "") != steps_to_produce:
        updates["customfield_10206"] = steps_to_produce
    if current.get("customfield_10207", "") != actual_result:
        updates["customfield_10207"] = actual_result
    if current.get("customfield_10208", "") != expected:
        updates["customfield_10208"] = expected

    if not updates:
        return False

    r = requests.put(
        f"{JIRA_URL}/rest/api/2/issue/{ticket_key}",
        headers=get_jira_headers(),
        json={"fields": updates},
        verify=False
    )
    if r.status_code == 204:
        changed_fields = ", ".join(updates.keys())
        print(f"  ✏️  티켓 업데이트: {ticket_key} [{platform_label}] ({changed_fields})")
        return True
    else:
        print(f"  ❌ 업데이트 실패 ({r.status_code}): {r.text[:200]}")
        return False

def format_ticket_cell(ticket_key, status):
    return f"{ticket_key} ({status})"

def get_jira_headers():
    token = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_TOKEN}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

def create_jira_ticket(config, row, platform, actual_result="", eng_row=None):
    title = row[COL_TITLE]
    precondition = row[COL_PRECONDITION]
    procedure = row[COL_PROCEDURE]
    expected = row[COL_EXPECTED]
    priority = row[COL_PRIORITY] if row[COL_PRIORITY] else "P3"
    feature = row[COL_FEATURE]
    sprint = get_current_sprint()

    release_version = config.get("release_version", "")

    if platform == "Android":
        platform_label = "Android"
        client_version = config.get("aos_version", "")
        device = config.get("device_model_aos", "")
        os_ver = config.get("os_version_aos", "")
        assignee_email = config.get("assignee_aos", "")
        epic_key = config.get("epic_aos", "")
    elif platform == "iOS":
        platform_label = "iOS"
        client_version = config.get("ios_version", "")
        device = config.get("device_model_ios", "")
        os_ver = config.get("os_version_ios", "")
        assignee_email = config.get("assignee_ios", "")
        epic_key = config.get("epic_ios", "")
    elif platform == "Web":
        platform_label = "Web"
        client_version = ""
        device = ""
        os_ver = ""
        assignee_email = config.get("assignee_web", "")
        epic_key = config.get("epic_web", "")
    else:  # BE
        platform_label = "BE"
        client_version = ""
        device = ""
        os_ver = ""
        assignee_email = config.get("assignee_be", "")
        epic_key = config.get("epic_be", "")

    assignee_id = assignee_email if assignee_email else None

    squad_name = config.get("squad_name", "")
    feature_name = config.get("feature_name", "")
    clean_title = re.sub(r'^(\[.*?\]\s*)+', '', title).strip()

    # Steps to Produce 템플릿 구성
    squad_env = config.get("squad_env", "")
    steps_lines = [f"* env : {squad_env}"]

    # TC Pre-condition에서 계정 정보 추출 (이메일 / 패스워드 패턴)
    account_match = re.search(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]+\s*/\s*\S+', precondition)
    if account_match:
        steps_lines.append(f"* test account : {account_match.group().strip()}")
    else:
        test_id = config.get("test_account_id", "")
        test_pwd = config.get("test_account_pwd", "")
        if test_id and test_pwd:
            steps_lines.append(f"* test account : {test_id} / {test_pwd}")
        else:
            steps_lines.append(f"* test account : ")

    # iOS 컨텐츠: ENG 시트 우선, 없으면 DeepL 번역
    translation_failed = False
    if platform == "iOS":
        if eng_row is not None:
            print("  📋 ENG 시트에서 iOS 컨텐츠 사용 중...")
            precondition_text = eng_row[COL_PRECONDITION] if len(eng_row) > COL_PRECONDITION else precondition
            procedure_text = eng_row[COL_PROCEDURE] if len(eng_row) > COL_PROCEDURE else procedure
            expected = eng_row[COL_EXPECTED] if len(eng_row) > COL_EXPECTED else expected
            eng_title = eng_row[COL_TITLE] if len(eng_row) > COL_TITLE else title
            clean_title = re.sub(r'^(\[.*?\]\s*)+', '', eng_title).strip()
        else:
            print("  🌐 iOS 티켓 번역 중...")
            try:
                precondition_text = translate_to_english(precondition)
                procedure_text = translate_to_english(procedure)
                actual_result = translate_to_english(actual_result)
                expected = translate_to_english(expected)
                clean_title = translate_to_english(clean_title)
            except Exception as e:
                print(f"  ⚠️ 번역 실패, 한국어로 생성: {e}")
                translation_failed = True
                precondition_text = precondition
                procedure_text = procedure
    else:
        precondition_text = precondition
        procedure_text = procedure

    summary = f"[{sprint.upper()}][{platform_label}][{squad_name}][{feature_name}] {clean_title}"

    if precondition_text:
        steps_lines.append(f"* precondition : {precondition_text}")

    steps_lines.append("")  # 빈 줄
    if procedure_text:
        steps_lines.append(procedure_text)

    steps_to_produce = "\n".join(steps_lines)
    payload = {
        "fields": {
            "project": {"key": "QA"},
            "issuetype": {"id": "10143"},
            "summary": summary,
            "priority": {"name": priority},
            "customfield_10199": {"value": sprint},           # Week
            "customfield_10201": {"value": platform_label},   # Platform
            "customfield_10200": {"value": "QA"},             # Detect Source
            "customfield_10205": {"value": config.get("reproducibility", "Always")},  # Issue Frequency
            "customfield_10206": steps_to_produce,            # Steps to Produce
            "customfield_10207": actual_result,               # Actual Result (시트 Actual Result 컬럼)
            "customfield_10208": expected,                    # Expected Result (TC Expected result)
            "customfield_10236": {"value": config.get("bug_type", "New Feature")},    # Issue Category (Internal)
            "customfield_10238": {"value": config.get("test_type", "Feature")},       # Test Type
            "customfield_10237": {"value": config.get("year", "2026")},               # Year
            "customfield_10221": {"value": config.get("server_env", "")},              # Server Env
            "customfield_10215": client_version,              # Client Version
            "customfield_10203": device,                      # Device / Browser
            "customfield_10204": os_ver,                      # OS Version
            "customfield_10219": release_version,                    # Release Version
            "customfield_10014": epic_key,                           # Epic Link (Parent)
            "customfield_10210": 0,                                  # QA Round
        }
    }

    if assignee_id:
        payload["fields"]["assignee"] = {"accountId": assignee_id}

    r = requests.post(
        f"{JIRA_URL}/rest/api/2/issue",
        headers=get_jira_headers(),
        json=payload,
        verify=False
    )

    if r.status_code == 201:
        ticket_key = r.json()["key"]
        print(f"  ✅ 티켓 생성: {ticket_key} [{platform_label}] {title[:50]}")
        requests.post(
            f"{JIRA_URL}/rest/api/2/issue/{ticket_key}/comment",
            headers=get_jira_headers(),
            json={"body": "/qa-auto-gen"},
            verify=False
        )
        return ticket_key, translation_failed
    else:
        print(f"  ❌ 티켓 생성 실패 ({r.status_code}): {r.text[:200]}")
        return None, False

# ─── 메인 polling 루프 ───────────────────────────────────────────────────────

def process_sheet(sheet, config, eng_rows=None):
    rows = sheet.get_all_values()
    headers = rows[0]

    # 헤더 행에 티켓 ID 컬럼 없으면 추가
    if len(headers) <= COL_IOS_TICKET:
        sheet.update_cell(1, COL_IOS_TICKET + 1, "iOS Ticket")
        sheet.update_cell(1, COL_AOS_TICKET + 1, "AOS Ticket")
        sheet.update_cell(1, COL_WEB_TICKET + 1, "Web Ticket")
        rows = sheet.get_all_values()

    new_tickets = 0

    for i, row in enumerate(rows[1:]):  # 헤더 제외
        while len(row) <= COL_BE_TICKET:
            row.append("")

        # ENG 시트의 동일 행 (헤더 포함 index i+1)
        eng_row = None
        if eng_rows is not None and i + 1 < len(eng_rows):
            eng_row = list(eng_rows[i + 1])
            while len(eng_row) <= COL_EXPECTED:
                eng_row.append("")

        checks = [
            (COL_IOS, COL_IOS_ACTUAL, COL_IOS_TICKET, "iOS"),
            (COL_AOS, COL_AOS_ACTUAL, COL_AOS_TICKET, "Android"),
            (COL_WEB, COL_WEB_ACTUAL, COL_WEB_TICKET, "Web"),
        ]

        # BE 티켓: iOS + AOS + Web 모두 Fail + BE Actual Result 있을 때
        all_fail = all(row[c].strip().lower() == "fail" for c in [COL_IOS, COL_AOS, COL_WEB])
        be_actual = row[COL_BE_ACTUAL].strip()
        be_ticket_cell = row[COL_BE_TICKET].strip()

        if all_fail and be_actual and not be_ticket_cell:
            ticket_key, trans_failed = create_jira_ticket(config, row, "BE", be_actual)
            if ticket_key:
                status = "번역실패" if trans_failed else (get_ticket_status(ticket_key) or "Ready")
                cell = format_ticket_cell(ticket_key, status)
                write_ticket_id(sheet, i, COL_BE_TICKET, cell)
                row[COL_BE_TICKET] = cell
                new_tickets += 1
                create_screenshot_folder("BE", ticket_key)
        elif be_ticket_cell:
            ticket_key = be_ticket_cell.split(" ")[0]
            attach_screenshots(ticket_key, "BE")
            update_jira_ticket(ticket_key, config, row, "BE", be_actual)
            status = get_ticket_status(ticket_key)
            be_pass = all(row[c].strip().lower() == "pass" for c in [COL_IOS, COL_AOS, COL_WEB])
            if be_pass and status and status not in ("Closed", "Not Issue"):
                close_ticket(ticket_key)
                status = "Closed"
            if status:
                new_cell = format_ticket_cell(ticket_key, status)
                if new_cell != be_ticket_cell:
                    write_ticket_id(sheet, i, COL_BE_TICKET, new_cell)
                    row[COL_BE_TICKET] = new_cell
                    print(f"  🔄 상태 변경: {new_cell}")

        for fail_col, actual_col, ticket_col, platform in checks:
            is_fail = row[fail_col].strip().lower() == "fail"
            has_actual = row[actual_col].strip() != ""
            cell_value = row[ticket_col].strip()
            already_created = cell_value != ""
            ios_eng = eng_row if platform == "iOS" else None

            if is_fail and has_actual and not already_created:
                ticket_key, trans_failed = create_jira_ticket(config, row, platform, row[actual_col].strip(), ios_eng)
                if ticket_key:
                    status = "번역실패" if trans_failed else (get_ticket_status(ticket_key) or "Ready")
                    cell = format_ticket_cell(ticket_key, status)
                    write_ticket_id(sheet, i, ticket_col, cell)
                    row[ticket_col] = cell
                    new_tickets += 1
                    create_screenshot_folder(platform, ticket_key)

            elif already_created:
                ticket_key = cell_value.split(" ")[0]
                attach_screenshots(ticket_key, platform)
                update_jira_ticket(ticket_key, config, row, platform, row[actual_col].strip(), ios_eng)
                # 시트에 Pass 입력 시 Jira 티켓 Closed 전환
                is_pass = row[fail_col].strip().lower() == "pass"
                status = get_ticket_status(ticket_key)
                if is_pass and status and status not in ("Closed", "Not Issue"):
                    close_ticket(ticket_key)
                    status = "Closed"
                if status:
                    new_cell = format_ticket_cell(ticket_key, status)
                    if new_cell != cell_value:
                        write_ticket_id(sheet, i, ticket_col, new_cell)
                        row[ticket_col] = new_cell
                        print(f"  🔄 상태 변경: {new_cell}")

    return new_tickets


def poll():
    print("🤖 QA Agent 시작 (5분마다 체크)")
    sheets = get_sheets()

    while True:
        try:
            config = load_config(CONFIG_FILE)
            config.setdefault("year", "2026")

            # ENG 시트 rows 로드 (KOR 시트의 iOS 티켓용)
            eng_rows = None
            if len(sheets) >= 2:
                eng_rows = sheets[0].get_all_values()

            total_new = 0
            for idx, sheet in enumerate(sheets):
                print(f"  📋 [{sheet.title}] 체크 중...")
                if idx == 0:
                    # ENG 시트: 이미 영어라 자기 자신을 eng_rows로 전달 (번역 불필요)
                    sheet_eng_rows = eng_rows if eng_rows is not None else sheet.get_all_values()
                else:
                    # KOR 시트: ENG 시트 rows 전달
                    sheet_eng_rows = eng_rows
                total_new += process_sheet(sheet, config, sheet_eng_rows)

            if total_new == 0:
                print(f"✓ 체크 완료 (다음 체크: 5분 후)")
            else:
                print(f"✓ {total_new}개 티켓 생성 완료")

        except Exception as e:
            print(f"❌ 오류 발생: {e}")

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    poll()
