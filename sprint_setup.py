import os
import re
import requests
import base64
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

def get_current_sprint():
    kst = timezone(timedelta(hours=9))
    week = datetime.now(kst).isocalendar()[1]
    return f"w{week}"

load_dotenv()

JIRA_URL   = os.getenv("JIRA_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_TOKEN = os.getenv("JIRA_TOKEN")
CONFIG_FILE = os.getenv("CONFIG_FILE")

PLATFORMS = ["iOS", "Android", "Web", "BE"]

PLATFORM_FIELD_MAP = {
    "iOS":     "iOS",
    "Android": "Android",
    "Web":     "Web",
}

def get_jira_headers():
    token = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_TOKEN}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

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

def update_config(path, key, value):
    with open(path, "r") as f:
        content = f.read()

    pattern = rf"^({re.escape(key)}\s*:\s*).*$"
    new_line = f"{key}: {value}"

    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, new_line, content, flags=re.MULTILINE)
    else:
        content += f"\n{new_line}"

    with open(path, "w") as f:
        f.write(content)

def get_my_account_id():
    r = requests.get(
        f"{JIRA_URL}/rest/api/2/myself",
        headers=get_jira_headers(),
        verify=False
    )
    return r.json()["accountId"]

def create_epic(config, platform, account_id):
    sprint      = get_current_sprint()
    squad_name  = config.get("squad_name", "")
    feature_name = config.get("feature_name", "")
    squad       = config.get("squad", "")
    year        = config.get("year", "2026")

    summary = f"[{sprint.upper()}][{platform}][{squad_name}] {feature_name}"

    payload = {
        "fields": {
            "project":           {"key": "QA"},
            "issuetype":         {"id": "10000"},           # Epic
            "summary":           summary,
            "customfield_10222": "-",                        # Custom Summary (필수값)
            "customfield_10199": {"value": sprint},          # Week
            "customfield_10201": {"value": platform},        # Platform
            "customfield_10237": {"value": year},            # Year
            "customfield_10238": {"value": "Feature"},       # Release Type
            "customfield_10219": "TBU",                      # Release Version
            "assignee":          {"accountId": account_id},
            "reporter":          {"accountId": account_id},
        }
    }

    r = requests.post(
        f"{JIRA_URL}/rest/api/2/issue",
        headers=get_jira_headers(),
        json=payload,
        verify=False
    )

    if r.status_code == 201:
        key = r.json()["key"]
        print(f"  ✅ Epic 생성: {key} [{platform}] {summary}")
        return key
    else:
        print(f"  ❌ Epic 생성 실패 ({r.status_code}): {r.text[:300]}")
        return None

def main():
    config = load_config(CONFIG_FILE)
    sprint = get_current_sprint()
    feature_name = config.get("feature_name", "")

    print(f"\n🚀 Sprint Setup - {sprint.upper()} / {feature_name}")
    print("=" * 50)

    account_id = get_my_account_id()

    config_key_map = {
        "iOS":     "epic_ios",
        "Android": "epic_aos",
        "Web":     "epic_web",
        "BE":      "epic_be",
    }

    for platform in PLATFORMS:
        epic_key = create_epic(config, platform, account_id)
        if epic_key:
            config_key = config_key_map[platform]
            update_config(CONFIG_FILE, config_key, epic_key)

    print("\n✅ config.md에 Epic 키 자동 업데이트 완료")
    print("=" * 50)

if __name__ == "__main__":
    main()
