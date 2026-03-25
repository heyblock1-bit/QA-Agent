import os
import re
import sys
import requests
import base64
import gspread
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

SPREADSHEET_URL = os.getenv("SPREADSHEET_URL")
SHEET_NAME = os.getenv("SHEET_NAME_KOR")
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE")
JIRA_URL = os.getenv("JIRA_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_TOKEN = os.getenv("JIRA_TOKEN")

COL_TITLE      = 4
COL_IOS        = 9
COL_IOS_TICKET = 11
COL_AOS        = 12
COL_AOS_TICKET = 14
COL_WEB        = 15
COL_WEB_TICKET = 17

PLATFORMS = [
    ("iOS",     COL_IOS, COL_IOS_TICKET),
    ("Android", COL_AOS, COL_AOS_TICKET),
    ("Web",     COL_WEB, COL_WEB_TICKET),
]

def get_jira_headers():
    token = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_TOKEN}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

def get_ticket_info(ticket_key):
    r = requests.get(
        f"{JIRA_URL}/rest/api/2/issue/{ticket_key}?fields=summary,status",
        headers=get_jira_headers(),
        verify=False
    )
    if r.status_code == 200:
        data = r.json()["fields"]
        return data["summary"], data["status"]["name"]
    return None, None

def get_sheet():
    creds = Credentials.from_service_account_file(
        CREDENTIALS_FILE,
        scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    )
    gc = gspread.authorize(creds)
    return gc.open_by_url(SPREADSHEET_URL).worksheet(SHEET_NAME)

def extract_ticket_key(cell_value):
    match = re.match(r"(QA-\d+)", cell_value.strip())
    return match.group(1) if match else None

def main():
    slack_mode = "--slack" in sys.argv

    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    sprint = f"W{now.isocalendar()[1]}"
    date_str = now.strftime("%Y-%m-%d %H:%M KST")

    if not slack_mode:
        print(f"\n📊 TC Coverage Report")
        print(f"📋 Sheet: {SHEET_NAME} | Sprint: {sprint}")
        print("=" * 50)

    sheet = get_sheet()
    rows = sheet.get_all_values()[1:]

    slack_lines = [
        f"TC Coverage Report | {sprint} | {date_str}",
        f"Sheet: {SHEET_NAME}",
        "",
    ]
    md_lines = [
        f"# TC Coverage Report", f"",
        f"- **Sheet**: {SHEET_NAME}", f"- **Sprint**: {sprint}", f"- **Generated**: {date_str}",
        f"", f"---", f"",
    ]
    en_lines = [
        f"# TC Coverage Report", f"",
        f"- **Sheet**: {SHEET_NAME}", f"- **Sprint**: {sprint}", f"- **Generated**: {date_str}",
        f"", f"---", f"",
    ]

    for platform, result_col, ticket_col in PLATFORMS:
        total = passed = failed = na = pending = blocked = incomplete = 0
        bugs = []

        for row in rows:
            while len(row) <= ticket_col:
                row.append("")
            result = row[result_col].strip().lower()
            title = row[COL_TITLE].strip()
            ticket_cell = row[ticket_col].strip()
            if not title:
                continue
            total += 1
            if result == "pass":         passed += 1
            elif result == "fail":       failed += 1
            elif result == "n/a":        na += 1
            elif result == "pending":    pending += 1
            elif result == "blocked":    blocked += 1
            else:                        incomplete += 1
            if ticket_cell:
                key = extract_ticket_key(ticket_cell)
                if key:
                    bugs.append((key, ticket_cell))

        if total == 0:
            continue

        pct = lambda n: round(n / total * 100)

        # 버그 정보 한 번만 조회
        bug_infos = []
        for key, _ in bugs:
            summary, status = get_ticket_info(key)
            bug_infos.append((key, summary, status))

        # 터미널 출력
        if not slack_mode:
            print(f"\n[{platform}]")
            print(f"  ✅ Pass    : {passed} ({pct(passed)}%)")
            print(f"  ❌ Fail    : {failed} ({pct(failed)}%)")
            print(f"  ➖ N/A     : {na} ({pct(na)}%)")
            print(f"  🕐 Pending : {pending} ({pct(pending)}%)")
            print(f"  🚫 Blocked : {blocked} ({pct(blocked)}%)")
            print(f"  ⬜ 미완료  : {incomplete} ({pct(incomplete)}%)")
            print(f"  📝 Total   : {total}")
            if bug_infos:
                print(f"  🐛 등록된 버그 ({len(bug_infos)}건):")
                for key, summary, status in bug_infos:
                    title_short = (summary[:55] + "...") if summary and len(summary) > 55 else (summary or "")
                    print(f"     {key} ({status})")
                    print(f"       └ {title_short}")
            else:
                print(f"  🐛 등록된 버그: 없음")

        # Slack 라인 (영어)
        slack_lines.append(f"[ {platform} ]  Total: {total}")
        slack_lines.append(f"• Pass: {passed} ({pct(passed)}%)")
        slack_lines.append(f"• Fail: {failed} ({pct(failed)}%)")
        slack_lines.append(f"• N/A: {na} ({pct(na)}%)")
        slack_lines.append(f"• Pending: {pending} ({pct(pending)}%)")
        slack_lines.append(f"• Blocked: {blocked} ({pct(blocked)}%)")
        slack_lines.append(f"• Incomplete: {incomplete} ({pct(incomplete)}%)")
        slack_lines.append(f"• Bugs: {len(bug_infos)}" if bug_infos else f"• Bugs: None")
        slack_lines.append("")

        # KOR MD 라인
        md_lines += [
            f"## {platform}", f"",
            f"| 항목 | 건수 | 비율 |", f"|------|------|------|",
            f"| ✅ Pass | {passed} | {pct(passed)}% |",
            f"| ❌ Fail | {failed} | {pct(failed)}% |",
            f"| ➖ N/A | {na} | {pct(na)}% |",
            f"| 🕐 Pending | {pending} | {pct(pending)}% |",
            f"| 🚫 Blocked | {blocked} | {pct(blocked)}% |",
            f"| ⬜ 미완료 | {incomplete} | {pct(incomplete)}% |",
            f"| 📝 Total | {total} | - |", f"",
        ]
        if bug_infos:
            md_lines += [f"### 🐛 등록된 버그 ({len(bug_infos)}건)", f""]
            for key, summary, status in bug_infos:
                md_lines += [f"- **{key}** ({status})", f"  - {summary}"]
            md_lines.append(f"")
        else:
            md_lines += [f"### 🐛 등록된 버그: 없음", f""]
        md_lines.append(f"---\n")

        # EN MD 라인
        en_lines += [
            f"## {platform}", f"",
            f"| Status | Count | Rate |", f"|--------|-------|------|",
            f"| ✅ Pass | {passed} | {pct(passed)}% |",
            f"| ❌ Fail | {failed} | {pct(failed)}% |",
            f"| ➖ N/A | {na} | {pct(na)}% |",
            f"| 🕐 Pending | {pending} | {pct(pending)}% |",
            f"| 🚫 Blocked | {blocked} | {pct(blocked)}% |",
            f"| ⬜ Incomplete | {incomplete} | {pct(incomplete)}% |",
            f"| 📝 Total | {total} | - |", f"",
        ]
        if bug_infos:
            en_lines += [f"### 🐛 Bugs ({len(bug_infos)})", f""]
            for key, summary, status in bug_infos:
                en_lines += [f"- **{key}** ({status})", f"  - {summary}"]
            en_lines.append(f"")
        else:
            en_lines += [f"### 🐛 Bugs: None", f""]
        en_lines.append(f"---\n")

    if slack_mode:
        print("\n".join(slack_lines))
    else:
        print("\n" + "=" * 50)

        base = os.path.dirname(__file__)
        date_suffix = now.strftime('%Y%m%d')

        kor_file = os.path.join(base, f"report_{date_suffix}.md")
        with open(kor_file, "w") as f:
            f.write("\n".join(md_lines))
        print(f"\n📄 KOR MD 저장 완료: {kor_file}")

        en_file = os.path.join(base, f"report_{date_suffix}_en.md")
        with open(en_file, "w") as f:
            f.write("\n".join(en_lines))
        print(f"📄 EN  MD 저장 완료: {en_file}")

if __name__ == "__main__":
    main()
