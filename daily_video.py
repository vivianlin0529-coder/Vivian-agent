"""
Vivi AI研習社 — 每日影片自動生產流程
任務一：搜尋英/日對標帳號
任務二：爆款選題分析與評分
任務三：YouTube 參考影片搜尋 + 寫入 Notion
+ 腳本生成 → 語音 → 影片渲染 → YouTube 上傳
"""

import os, re, json, datetime, base64, time, pickle
from pathlib import Path
import requests
from google import genai as genai_sdk
from google.genai import types as genai_types

# ── 環境變數 ──────────────────────────────

GEMINI_KEY       = os.getenv("GEMINI_API_KEY", "")
ELEVENLABS_KEY   = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE = os.getenv("ELEVENLABS_VOICE_ID", "")   # 格式如 21m00Tcm4TlvDq8ikWAM
YOUTUBE_API_KEY  = os.getenv("YOUTUBE_API_KEY", "")
NOTION_TOKEN     = os.getenv("NOTION_TOKEN", "")
NOTION_VIDEO_DB  = os.getenv("NOTION_VIDEO_DB", "")

# GitHub Actions：從 base64 secret 還原 YouTube token
_yt_b64 = os.getenv("YOUTUBE_TOKEN_B64", "")
if _yt_b64:
    with open("token.pickle", "wb") as _f:
        _f.write(base64.b64decode(_yt_b64))

# ── 驗證必要變數 ──────────────────────────

def _require(name: str, value: str):
    if not value:
        raise EnvironmentError(f"❌ 缺少環境變數：{name}")

_require("GEMINI_API_KEY",    GEMINI_KEY)
_require("ELEVENLABS_API_KEY", ELEVENLABS_KEY)
_require("ELEVENLABS_VOICE_ID", ELEVENLABS_VOICE)

# ── Gemini 初始化 ─────────────────────────

gemini = genai_sdk.Client(api_key=GEMINI_KEY)
GEMINI_MODEL = "gemini-2.5-flash"

# ── 品牌視覺設定 ──────────────────────────

BG_COLOR     = (245, 240, 235)
ACCENT_COLOR = (80,  60,  40)
BRAND_COLOR  = (180, 100, 60)
WIDTH, HEIGHT = 1080, 1920
LINE_CHARS    = 14


# ── 共用工具 ──────────────────────────────

def _gemini_json(prompt: str, use_search: bool = False, array: bool = False):
    """呼叫 Gemini，自動重試，回傳 dict 或 list。"""
    config_kwargs = {
        "response_mime_type": "application/json",
    }
    if use_search:
        config_kwargs["tools"] = [genai_types.Tool(google_search=genai_types.GoogleSearch())]
        # 啟用 google_search 時不可同時指定 response_mime_type（API 限制）
        config_kwargs.pop("response_mime_type", None)

    config = genai_types.GenerateContentConfig(**config_kwargs)

    for attempt in range(3):
        try:
            msg = gemini.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=config,
            )
            text = msg.text
            pattern = r'\[[\s\S]+\]' if array else r'\{[\s\S]+\}'
            match = re.search(pattern, text)
            if match:
                return json.loads(match.group())
            return [] if array else {}
        except Exception as e:
            print(f"  ⚠️ Gemini 第 {attempt+1} 次失敗：{e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
    return [] if array else {}


def _safe_post(url: str, *, headers: dict, json_body: dict = None,
               data: bytes = None, timeout: int = 60) -> requests.Response:
    """帶重試的 POST。"""
    for attempt in range(3):
        try:
            resp = requests.post(
                url,
                headers=headers,
                json=json_body,
                data=data,
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            print(f"  ⚠️ 請求第 {attempt+1} 次失敗：{e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise


# ═══════════════════════════════════════════
# 任務一：對標帳號研究（啟用 Google Search grounding）
# ═══════════════════════════════════════════

def research_benchmark_accounts() -> dict:
    print("\n🔍 任務一：搜尋對標帳號...")

    prompt = """
你是 Vivi AI研習社的內容策略師。Vivi 是台灣非工科出身的職場 PM，
YouTube 頻道定位：AI 工具教學 × 職場效率 × 普通人也能用。

請用 Google 搜尋，列出 AI 工具教學 & AI 變現領域的真實對標帳號：

**英文帳號（3個）：**
選訂閱數 10 萬以上、內容以「非工程師也能用 AI」或「AI 副業」為主的帳號。
每個附：帳號名稱、YouTube 頻道 URL、定位一句話、代表影片標題

**日文帳號（3個）：**
選近期活躍、主題為「AI活用」「AI副業」的帳號。
每個附：帳號名稱、YouTube 頻道 URL、定位一句話、代表影片標題

輸出 JSON 格式：
{
  "english": [{"name":"...", "url":"...", "positioning":"...", "sample_video":"..."}, ...],
  "japanese": [{"name":"...", "url":"...", "positioning":"...", "sample_video":"..."}, ...]
}
"""
    result = _gemini_json(prompt, use_search=True)
    print(f"  找到英文帳號：{len(result.get('english', []))} 個")
    print(f"  找到日文帳號：{len(result.get('japanese', []))} 個")
    return result


# ═══════════════════════════════════════════
# 任務二：爆款選題分析
# ═══════════════════════════════════════════

def analyze_viral_topics(manual_topic: str = "") -> list:
    print("\n💡 任務二：爆款選題分析...")

    if manual_topic:
        print(f"  使用指定選題：{manual_topic}")
        return [{"title": manual_topic, "score": 10, "keyword": manual_topic,
                 "appeal": "用戶指定", "algorithm": "手動選題", "reason": "手動指定"}]

    prompt = """
根據 2025-2026 最新 AI 趨勢，針對台灣非技術背景上班族，
為「Vivi AI研習社」YouTube 頻道提供 5 個爆款短影片選題。

選題原則：
- 符合 Vivi 人設：非工科 PM、職場小白視角、文科語言
- 關鍵字有搜尋量、近期熱度高
- 60 秒內能說清楚
- 台灣觀眾有共鳴

每個選題附：
1. 影片標題（台灣口語化）
2. 核心吸引力（為什麼觀眾會點）
3. 演算法潛力（搜尋量高/競爭低/趨勢中）
4. 主要關鍵字（用於 YouTube 搜尋）
5. 綜合評分（1-10）+ 評分理由

輸出 JSON 陣列：
[
  {
    "title": "...",
    "appeal": "...",
    "algorithm": "...",
    "keyword": "...",
    "score": 9,
    "reason": "..."
  }
]
"""
    topics = _gemini_json(prompt, array=True)
    if not topics:
        topics = [{"title": "非工程師用 AI 做出副業的完整流程", "score": 9,
                   "keyword": "AI副業 非工程師", "appeal": "貼近大眾痛點",
                   "algorithm": "搜尋量高", "reason": "fallback"}]
    topics.sort(key=lambda x: x.get("score", 0), reverse=True)
    return topics


# ═══════════════════════════════════════════
# 任務三：YouTube 參考影片搜尋
# ═══════════════════════════════════════════

def search_youtube_videos(keyword: str, max_results: int = 5) -> list:
    print(f"\n🎥 搜尋 YouTube 參考影片：{keyword}")
    if not YOUTUBE_API_KEY:
        print("  ⚠️ 未設定 YOUTUBE_API_KEY，跳過搜尋")
        return []

    search_resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "part": "snippet",
            "q": keyword,
            "type": "video",
            "order": "viewCount",
            "maxResults": max_results * 2,
            "regionCode": "TW",
            "relevanceLanguage": "zh-Hant",
            "key": YOUTUBE_API_KEY,
        },
        timeout=20,
    )
    search_resp.raise_for_status()
    items = search_resp.json().get("items", [])
    if not items:
        return []

    video_ids = ",".join([i["id"]["videoId"] for i in items])
    stats_resp = requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={"part": "statistics,snippet", "id": video_ids, "key": YOUTUBE_API_KEY},
        timeout=20,
    )
    stats_resp.raise_for_status()
    stats_map = {v["id"]: v for v in stats_resp.json().get("items", [])}

    videos = []
    for item in items[:max_results]:
        vid_id = item["id"]["videoId"]
        stat   = stats_map.get(vid_id, {})
        stats  = stat.get("statistics", {})
        snippet = stat.get("snippet", item.get("snippet", {}))
        videos.append({
            "title":        snippet.get("title", ""),
            "channel":      snippet.get("channelTitle", ""),
            "views":        int(stats.get("viewCount", 0)),
            "published_at": snippet.get("publishedAt", "")[:10],
            "url":          f"https://www.youtube.com/watch?v={vid_id}",
            "video_id":     vid_id,
        })

    return sorted(videos, key=lambda x: x["views"], reverse=True)


def analyze_video_outliers(videos: list, keyword: str) -> list:
    print("  🤖 分析影片異常值...")
    if not videos:
        return videos

    video_summary = json.dumps(
        [{"title": v["title"], "channel": v["channel"],
          "views": v["views"], "date": v["published_at"]} for v in videos],
        ensure_ascii=False,
    )

    prompt = f"""
以下是 YouTube 關鍵字「{keyword}」的熱門影片，請分析每部影片播放量為何特別高。

{video_summary}

對每部影片，以 1-2 句話說明異常值原因（標題用詞、發布時機、縮圖設計、頻道背書等）。

輸出 JSON 陣列，每個元素只有 "title" 和 "outlier_reason" 兩個 key。
"""
    analyses = _gemini_json(prompt, array=True)
    analysis_map = {a["title"]: a.get("outlier_reason", "") for a in analyses}
    for v in videos:
        v["outlier_reason"] = analysis_map.get(v["title"], "")
    return videos


# ═══════════════════════════════════════════
# 寫入 Notion（欄位型別修正）
# ═══════════════════════════════════════════

def write_to_notion(videos: list, benchmark: dict, topic_title: str):
    print("\n📝 寫入 Notion...")
    if not NOTION_TOKEN or not NOTION_VIDEO_DB:
        print("  ⚠️ 未設定 NOTION_TOKEN 或 NOTION_VIDEO_DB，跳過")
        return

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    for v in videos:
        # 日期格式驗證
        pub_date = v.get("published_at", "")
        date_prop = {"date": {"start": pub_date}} if pub_date else {"rich_text": []}

        page = {
            "parent": {"database_id": NOTION_VIDEO_DB},
            "properties": {
                "影片標題":  {"title":     [{"text": {"content": v["title"]}}]},
                "博主名稱":  {"rich_text": [{"text": {"content": v["channel"]}}]},
                "播放量":    {"number":    v["views"]},           # ✅ number 欄位，可排序
                "上傳日期":  date_prop,                           # ✅ date 欄位
                "影片連結":  {"url":       v["url"]},
                "異常值分析":{"rich_text": [{"text": {"content": v.get("outlier_reason", "")}}]},
                "對應選題":  {"rich_text": [{"text": {"content": topic_title}}]},
            },
        }
        try:
            resp = requests.post(
                "https://api.notion.com/v1/pages",
                headers=headers,
                json=page,
                timeout=20,
            )
            if resp.status_code == 200:
                print(f"  ✅ 寫入：{v['title'][:40]}")
            else:
                print(f"  ❌ 失敗 {resp.status_code}：{resp.text[:120]}")
        except requests.RequestException as e:
            print(f"  ❌ 網路錯誤：{e}")


# ═══════════════════════════════════════════
# 腳本生成
# ═══════════════════════════════════════════

def generate_script(topic: dict) -> tuple[str, str, str, list]:
    print(f"\n✍️ 生成腳本：{topic['title']}")
    prompt = f"""
你是 Vivi（林怡伶）的 AI 分身，幫她寫 YouTube 短影片腳本。

選題：{topic['title']}
核心吸引力：{topic.get('appeal', '')}

**Vivi 人設**：文科出身、非工科 PM、職場小白視角，語言口語化不用術語，
每集強調「我親自測試過，幫我省了 X 小時」的真實感。

⚠️ 重要原則：這是教學影片，不是廣告。
- 必須包含「觀眾今天就能動手做」的具體步驟
- 每個步驟要說清楚「去哪裡」「按什麼」「輸入什麼」
- 禁止空泛的行銷語言，例如「超強工具」「改變你的人生」
- 用 Vivi 親身操作的第一人稱語氣：「我是這樣做的」「你只要這樣⋯」

請寫一個 60 秒短影片腳本（約 300-330 字），結構：
1. 勾子（10秒）：用一個具體數字或反直覺的真實結果開場
2. 共鳴（5秒）：點出觀眾的痛點，一句話就好
3. 實際步驟（35秒）：3 個具體可操作的步驟
4. 行動呼籲（10秒）：留言區互動問題 + 訂閱 + Vivi 自介

同時輸出：
- 影片標題（口語化，適合台灣觀眾）
- YouTube 說明欄（含 hashtag）
- Tags 陣列

輸出 JSON：
{{
  "script": "...",
  "title": "...",
  "description": "...",
  "tags": ["...", "..."]
}}
"""
    data = _gemini_json(prompt)
    return (
        data.get("script", ""),
        data.get("title", topic["title"]),
        data.get("description", ""),
        data.get("tags", ["AI工具", "Vivi AI研習社"]),
    )


# ═══════════════════════════════════════════
# 語音生成（ElevenLabs）
# ═══════════════════════════════════════════

def generate_voice(script: str, output: str = "voice.mp3") -> str:
    print("🎙️  生成語音（ElevenLabs）...")
    if not ELEVENLABS_VOICE:
        raise EnvironmentError("ELEVENLABS_VOICE_ID 未設定")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE}"
    headers = {"xi-api-key": ELEVENLABS_KEY, "Content-Type": "application/json"}
    payload = {
        "text": script,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    resp = _safe_post(url, headers=headers, json_body=payload, timeout=120)
    with open(output, "wb") as f:
        f.write(resp.content)
    print(f"  ✅ 語音儲存：{output} ({Path(output).stat().st_size // 1024} KB)")
    return output


# ═══════════════════════════════════════════
# 影片渲染（使用 video_renderer，內含動畫字幕）
# ═══════════════════════════════════════════

def render_video(audio_path: str, script: str, output: str = "video_final.mp4") -> str:
    print("🎬 渲染影片...")
    from video_renderer import render_animated_video
    return render_animated_video(audio_path, script, output)


# ═══════════════════════════════════════════
# YouTube 上傳
# ═══════════════════════════════════════════

def upload_youtube(video_path: str, title: str, description: str, tags: list) -> str:
    print("📤 上傳 YouTube...")
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds = None
    if Path("token.pickle").exists():
        with open("token.pickle", "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise EnvironmentError(
                "YouTube token 無效。請在本機執行一次 OAuth 授權，"
                "再將 token.pickle 的 base64 存為 YOUTUBE_TOKEN_B64 secret。"
            )

    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title":       title[:100],           # YouTube 標題上限 100 字元
            "description": description[:5000],
            "tags":        tags[:500],
            "categoryId":  "28",                  # Science & Technology
        },
        "status": {"privacyStatus": "public"},
    }
    media   = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(
        part=",".join(body.keys()), body=body, media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  上傳進度：{int(status.progress() * 100)}%")

    url = f"https://youtu.be/{response['id']}"
    print(f"  ✅ 上傳完成：{url}")

    # 輸出給 GitHub Actions workflow
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"youtube_url={url}\n")
            f.write(f"video_title={title}\n")

    return url


# ═══════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════

def main():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n🚀 Vivi AI研習社 每日影片自動生產流程啟動")
    print(f"   {now} 台北時間\n")

    manual_topic = os.getenv("MANUAL_TOPIC", "").strip()

    # 任務一：對標帳號研究
    benchmark = research_benchmark_accounts()

    # 任務二：選題分析
    topics = analyze_viral_topics(manual_topic)
    best   = topics[0] if topics else {
        "title": "AI 工具入門", "keyword": "AI工具", "score": 8,
        "appeal": "", "algorithm": "", "reason": "fallback",
    }
    print(f"\n  ⭐ 最高分選題（{best.get('score',0)} 分）：{best['title']}")
    for i, t in enumerate(topics, 1):
        print(f"  {i}. [{t.get('score',0)}分] {t['title']}")

    # 任務三：YouTube 搜尋 + Notion 寫入
    keyword = best.get("keyword") or best["title"]
    videos  = search_youtube_videos(keyword, max_results=5)
    if videos:
        videos = analyze_video_outliers(videos, keyword)
        write_to_notion(videos, benchmark, best["title"])

    # 生成腳本
    script, title, description, tags = generate_script(best)

    # 儲存 meta（含日期戳，避免覆蓋）
    date_str  = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    meta_path = f"video_meta_{date_str}.json"
    meta = {
        "title": title, "description": description, "tags": tags,
        "topic": best, "benchmark": benchmark, "reference_videos": videos,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"\n  📄 Meta 儲存：{meta_path}")

    # 語音生成
    audio_path = generate_voice(script)

    # 影片渲染
    video_path = render_video(audio_path, script)

    # YouTube 上傳
    youtube_url = upload_youtube(video_path, title, description, tags)

    print(f"\n🎉 完成！影片已上架：{youtube_url}")
    print(f"   選題：{title}")
    return youtube_url


if __name__ == "__main__":
    main()
