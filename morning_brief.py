"""
Vivi AI研習社 — 每日晨報
每天早上 8 點（台灣時間）自動執行，產出今日簡報
"""

import os, json, datetime, pickle, base64
from pathlib import Path
from google import genai as genai_sdk
import requests

# ── 工具函數 ──────────────────────────────

def get_google_creds():
    """從環境變數重建 Google OAuth Credentials"""
    from google.oauth2.credentials import Credentials
    token_json = os.getenv("GMAIL_TOKEN_JSON", "")
    if not token_json:
        return None
    data = json.loads(base64.b64decode(token_json))
    return Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes", [])
    )

# ── Step 1：Gmail 未讀信件 ────────────────

def fetch_gmail(creds, max_results=10):
    from googleapiclient.discovery import build
    print("📧 讀取 Gmail...")
    try:
        service = build("gmail", "v1", credentials=creds)
        result = service.users().messages().list(
            userId="me", q="is:unread", maxResults=max_results
        ).execute()
        messages = result.get("messages", [])
        emails = []
        for m in messages[:5]:
            msg = service.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            emails.append({
                "subject": headers.get("Subject", "(無主旨)"),
                "from":    headers.get("From", ""),
                "date":    headers.get("Date", ""),
            })
        return emails
    except Exception as e:
        print(f"  Gmail 錯誤: {e}")
        return []

# ── Step 2：Google Calendar 今日行程 ───────

def fetch_calendar(creds):
    from googleapiclient.discovery import build
    print("📅 讀取 Calendar...")
    try:
        service = build("calendar", "v3", credentials=creds)
        now = datetime.datetime.utcnow().isoformat() + "Z"
        end = (datetime.datetime.utcnow() + datetime.timedelta(hours=16)).isoformat() + "Z"
        events_result = service.events().list(
            calendarId="primary", timeMin=now, timeMax=end,
            maxResults=10, singleEvents=True, orderBy="startTime"
        ).execute()
        events = []
        for e in events_result.get("items", []):
            start = e["start"].get("dateTime", e["start"].get("date", ""))
            events.append({
                "title": e.get("summary", "(無標題)"),
                "start": start,
                "location": e.get("location", ""),
            })
        return events
    except Exception as e:
        print(f"  Calendar 錯誤: {e}")
        return []

# ── Step 3：Notion 今日待辦 ───────────────

def fetch_notion_todos():
    print("📋 讀取 Notion 待辦...")
    notion_token = os.getenv("NOTION_TOKEN", "")
    db_id = os.getenv("NOTION_JOURNAL_DB", "")
    if not notion_token or not db_id:
        return []
    try:
        today = datetime.date.today().isoformat()
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{db_id}/query",
            headers={
                "Authorization": f"Bearer {notion_token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json"
            },
            json={"filter": {"property": "Date", "date": {"equals": today}}}
        )
        items = []
        for page in resp.json().get("results", []):
            props = page.get("properties", {})
            title_prop = props.get("Name", props.get("Task", props.get("Title", {})))
            title_content = title_prop.get("title", [])
            if title_content:
                items.append(title_content[0].get("plain_text", ""))
        return items
    except Exception as e:
        print(f"  Notion 錯誤: {e}")
        return []

# ── Step 4：Claude 生成簡報 ───────────────

def generate_report(emails, events, todos):
    print("🤖 Gemini 生成簡報...")
    gemini = genai_sdk.Client(api_key=os.getenv("GEMINI_API_KEY", ""), http_options={"api_version": "v1"})
    today = datetime.datetime.now().strftime("%Y-%m-%d %A")

    prompt = f"""
你是 Vivian 的 AI 助理，請根據以下資訊生成今日晨報。

今天日期：{today}（台北時間）

## Gmail 未讀信件（共 {len(emails)} 封）
{json.dumps(emails, ensure_ascii=False, indent=2)}

## 今日行程（共 {len(events)} 個）
{json.dumps(events, ensure_ascii=False, indent=2)}

## Notion 今日待辦（共 {len(todos)} 項）
{json.dumps(todos, ensure_ascii=False)}

請用繁體中文，以條列式輸出「今日晨報」，包含：
1. 📧 重要信件摘要（最多 3 封，標註是否需要回覆）
2. 📅 今日行程時間軸
3. ✅ 今日待辦優先順序
4. 💡 今日一句話提醒（根據行程和待辦給 Vivian 的建議）

格式要簡潔，適合早上快速掃瞄。
"""

    msg = gemini.models.generate_content(model="gemini-1.5-flash", contents=prompt)
    return msg.text

# ── 主流程 ────────────────────────────────

def main():
    print("\n🌅 Vivi 晨報系統啟動\n")
    creds = get_google_creds()
    emails = fetch_gmail(creds) if creds else []
    events = fetch_calendar(creds) if creds else []
    todos  = fetch_notion_todos()

    report = generate_report(emails, events, todos)
    print("\n" + "="*50)
    print(report)
    print("="*50 + "\n")

    # 儲存報告到檔案（GitHub Actions artifact 用）
    with open("morning_report.md", "w", encoding="utf-8") as f:
        f.write(f"# Vivi 晨報 {datetime.date.today()}\n\n")
        f.write(report)
    print("✅ 晨報已儲存：morning_report.md")

if __name__ == "__main__":
    main()
