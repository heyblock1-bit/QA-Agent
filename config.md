# QA Agent Config
스프린트 시작 시 아래 값들을 업데이트하세요.
sprint은 KST 기준 현재 주차로 자동 계산됩니다.

---

## Jira 필드

server_env: Luke                        # Server Env        (customfield_10221)
release_version: 3.15.1                 # Release Version   (customfield_10219)
bug_type: New Feature                   # Issue Category    (customfield_10236)
reproducibility: Always                 # Issue Frequency   (customfield_10205)
test_type: Feature                      # Test Type         (customfield_10238)

---

## 티켓 설정

squad_name: CoreUX                      # 티켓 제목 prefix [squad_name]
feature_name: TP/SL Revamp Phase 3      # 티켓 제목 prefix [feature_name]
squad_env: squad-tpsl                   # Steps to Produce > env 값

---

## Test Account

test_account_id: jiseon+t1@prex.io
test_account_pwd: Swtest1!

---

## Assignee (Jira accountId)

assignee_ios: 712020:014a5487-2e74-407b-b2a8-1f6b244f8874
assignee_aos: 633408bd7f85f16777a01a9e
assignee_web: 712020:4e59a5b9-7240-4bb2-9b2e-292083c958da
assignee_be:  63a564ca6ad11358a0977c8c

---

## Epic (Parent Issue)

epic_ios: QA-19945
epic_aos: QA-19946
epic_web: QA-19947
epic_be:  QA-19948

---

## Device Info

# Android
aos_version: 3.14.103.tpsl-phase3
device_model_aos: Galaxy S24
os_version_aos: 15

# iOS
ios_version: 3.14.100 (9219)
device_model_ios: iPhone 16
os_version_ios: 26