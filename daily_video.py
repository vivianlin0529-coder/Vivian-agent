"""
Vivi AI研習社 — 每日影片自動生產流程
輸出：16:9 YouTube 標準教學影片（步驟圖卡 + 實際截圖）

EXECUTION_MODE:
  PREVIEW（預設）— 生成影片但不上傳 YouTube，輸出 daily_preview_video.mp4 供確認
  FULL           — 重新生成並上傳 YouTube
"""

import os, re, json, datetime, base64, time, pickle, shutil
from pathlib import Path
import requests
from google import genai as genai_sdk
from google.genai import types as genai_types

# ── 執行模式 ──────────────────────────────────────────────────────
EXECUTION_MODE = os.environ.get("EXECUTION_MODE", "PREVIEW").upper()
print(f"\n⚙️  執行模式：{EXECUTION_MODE}")

# ── 環境變數 ──────────────────────────────
GEMINI_KEY       = os.getenv("GEMINI_API_KEY", "")
GOOGLE_TTS_KEY   = os.getenv("YOUTUBE_API_KEY", "")
GOOGLE_TTS_VOICE = os.getenv("GOOGLE_TTS_VOICE", "cmn-TW-Wavenet-A")
YOUTUBE_API_KEY  = os.getenv("YOUTUBE_API_KEY", "")
NOTION_TOKEN     = os.getenv("NOTION_TOKEN", "")
NOTION_VIDEO_DB  = os.getenv("NOTION_VIDEO_DB", "")

# GitHub Actions：從 base64 secret 還原 YouTube token
_yt_b64 = os.getenv("YOUTUBE_TOKEN_B64", "")
if _yt_b64:
    with open("token.pickle", "wb") as _f:
        _f.write(base64.b64decode(_yt_b64))

def _require(name, value):
    if not value:
        raise EnvironmentError(f"❌ 缺少環境變數：{name}")

_require("GEMINI_API_KEY", GEMINI_KEY)
_require("YOUTUBE_API_KEY", GOOGLE_TTS_KEY)

# ── Gemini 初始化 ─────────────────────────
gemini = genai_sdk.Client(api_key=GEMINI_KEY)
GEMINI_MODEL = "gemini-2.5-flash"

# ── 共用工具 ──────────────────────────────
def _gemini_json(prompt: str, use_search: bool = False, array: bool = False):
    config_kwargs = {}
    if use_search:
        config_kwargs["tools"] = [genai_types.Tool(google_search=genai_types.GoogleSearch())]
    else:
        config_kwargs["response_mime_type"] = "application/json"
    config = genai_types.GenerateContentConfig(**config_kwargs)
    for attempt in range(3):
        try:
            msg = gemini.models.generate_content(
                model=GEMINI_MODEL, contents=prompt, config=config)
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

def _safe_post(url, *, headers, json_body=None, timeout=60):
    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=json_body, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            print(f"  ⚠️ 請求第 {attempt+1} 次失敗：{e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise

# ═══════════════════════════════════════════
# 任務一：對標帳號研究
# ═══════════════════════════════════════════
def research_benchmark_accounts() -> dict:
    print("\n🔍 任務一：搜尋對標帳號...")
    prompt = """
你是 Vivi AI研習社的內容策略師。請用 Google 搜尋，列出 AI 工具教學 & AI 變現領域的真實對標帳號。
英文帳號（3個）：訂閱數 10 萬以上、以「非工程師也能用 AI」或「AI 副業」為主。
日文帳號（3個）：近期活躍、主題為「AI活用」「AI副業」。
每個附：帳號名稱、YouTube 頻道 URL、定位一句話、代表影片標題
輸出 JSON：
{"english":[{"name":"...","url":"...","positioning":"...","sample_video":"..."}],
 "japanese":[{"name":"...","url":"...","positioning":"...","sample_video":"..."}]}
"""
    result = _gemini_json(prompt, use_search=True)
    print(f"  英文帳號：{len(result.get('english',[]))} 個 / 日文帳號：{len(result.get('japanese',[]))} 個")
    return result

# ═══════════════════════════════════════════
# 任務二：爆款選題分析
# ═══════════════════════════════════════════
def analyze_viral_topics(manual_topic: str = "") -> list:
    print("\n💡 任務二：爆款選題分析...")
    if manual_topic:
        return [{"title": manual_topic, "score": 10, "keyword": manual_topic,
                 "appeal": "用戶指定", "algorithm": "手動選題", "reason": "手動指定",
                 "tool": "Claude"}]
    prompt = """
針對台灣非技術背景上班族，為「Vivi AI研習社」提供 5 個爆款短影片選題。
每個選題必須：
- 是「某個 AI 工具的具體操作教學」（例如：用 Claude 整理會議記錄、用 Gamma 做簡報）
- 有 3 個可截圖示意的操作步驟
- 60 秒內能說清楚
- 指定一個主要工具（Claude / Gamma / Notion AI / ChatGPT / Canva AI 等）
輸出 JSON 陣列：
[{"title":"...","appeal":"...","algorithm":"...","keyword":"...","tool":"...","score":9,"reason":"..."}]
"""
    topics = _gemini_json(prompt, array=True)
    if not topics:
        topics = [{"title": "3步驟用Claude整理會議記錄，省下2小時", "score": 9,
                   "keyword": "Claude 教學 會議記錄", "tool": "Claude",
                   "appeal": "具體省時數字", "algorithm": "搜尋量高", "reason": "fallback"}]
    topics.sort(key=lambda x: x.get("score", 0), reverse=True)
    return topics

# ═══════════════════════════════════════════
# 任務三：YouTube 參考影片搜尋
# ═══════════════════════════════════════════
def search_youtube_videos(keyword: str, max_results: int = 5) -> list:
    print(f"\n🎥 搜尋 YouTube 參考影片：{keyword}")
    if not YOUTUBE_API_KEY:
        print("  ⚠️ 未設定 YOUTUBE_API_KEY，跳過")
        return []
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={"part":"snippet","q":keyword,"type":"video","order":"viewCount",
                    "maxResults":max_results*2,"regionCode":"TW",
                    "relevanceLanguage":"zh-Hant","key":YOUTUBE_API_KEY}, timeout=20)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return []
        video_ids = ",".join([i["id"]["videoId"] for i in items])
        stats_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part":"statistics,snippet","id":video_ids,"key":YOUTUBE_API_KEY}, timeout=20)
        stats_resp.raise_for_status()
        stats_map = {v["id"]: v for v in stats_resp.json().get("items", [])}
        videos = []
        for item in items[:max_results]:
            vid_id = item["id"]["videoId"]
            stat = stats_map.get(vid_id, {})
            snippet = stat.get("snippet", item.get("snippet", {}))
            videos.append({
                "title": snippet.get("title",""),
                "channel": snippet.get("channelTitle",""),
                "views": int(stat.get("statistics",{}).get("viewCount",0)),
                "published_at": snippet.get("publishedAt","")[:10],
                "url": f"https://www.youtube.com/watch?v={vid_id}",
                "video_id": vid_id,
            })
        return sorted(videos, key=lambda x: x["views"], reverse=True)
    except Exception as e:
        print(f"  ⚠️ YouTube 搜尋失敗：{e}")
        return []

def analyze_video_outliers(videos: list, keyword: str) -> list:
    if not videos:
        return videos
    summary = json.dumps([{"title":v["title"],"views":v["views"]} for v in videos], ensure_ascii=False)
    prompt = f'分析 YouTube 關鍵字「{keyword}」熱門影片異常值原因。\n{summary}\n輸出 JSON 陣列：[{{"title":"...","outlier_reason":"..."}}]'
    analyses = _gemini_json(prompt, array=True)
    amap = {a["title"]: a.get("outlier_reason","") for a in analyses}
    for v in videos:
        v["outlier_reason"] = amap.get(v["title"],"")
    return videos

def write_to_notion(videos: list, benchmark: dict, topic_title: str):
    print("\n📝 寫入 Notion...")
    if not NOTION_TOKEN or not NOTION_VIDEO_DB:
        print("  ⚠️ 跳過（未設定 NOTION 環境變數）")
        return
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}",
                "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    for v in videos:
        pub_date = v.get("published_at","")
        page = {
            "parent": {"database_id": NOTION_VIDEO_DB},
            "properties": {
                "影片標題": {"title": [{"text":{"content": v["title"]}}]},
                "博主名稱": {"rich_text": [{"text":{"content": v["channel"]}}]},
                "播放量": {"number": v["views"]},
                "上傳日期": {"date": {"start": pub_date}} if pub_date else {"rich_text":[]},
                "影片連結": {"url": v["url"]},
                "異常值分析":{"rich_text": [{"text":{"content": v.get("outlier_reason","")}}]},
                "對應選題": {"rich_text": [{"text":{"content": topic_title}}]},
            }
        }
        try:
            resp = requests.post("https://api.notion.com/v1/pages",
                                 headers=headers, json=page, timeout=20)
            icon = "✅" if resp.status_code == 200 else f"❌{resp.status_code}"
            print(f"  {icon} {v['title'][:40]}")
        except Exception as e:
            print(f"  ❌ {e}")

# ═══════════════════════════════════════════
# 腳本生成（結構化教學步驟）
# ═══════════════════════════════════════════
def generate_script(topic: dict) -> tuple:
    print(f"\n✍️ 生成教學腳本：{topic['title']}")
    tool = topic.get("tool", "AI工具")
    prompt = f"""
你是 Vivi（林怡伶）的 AI 分身，幫她寫 YouTube 教學影片腳本。
選題：{topic['title']}
主要工具：{tool}

⚠️ 這是真實操作教學，不是廣告：
- 每個步驟必須說清楚：去哪個網址 / 點哪個按鈕 / 輸入什麼文字 / 會看到什麼結果
- 禁止行銷語言（「超強」「改變人生」「神器」）
- Vivi 親身第一人稱語氣

輸出包含：
1. 旁白腳本（hook + 3個步驟 + CTA，約300字，觀眾聽的）
2. 每個步驟的結構化資料（畫面顯示用）

JSON 格式：
{{
  "title": "影片標題（口語化，含數字或具體結果）",
  "description": "YouTube說明欄（含 #hashtag）",
  "tags": ["標籤1","標籤2"],
  "narration": "完整旁白腳本（300字，口語化，觀眾跟著做）",
  "hook": "開場白（10秒，用具體數字）",
  "steps": [
    {{
      "num": 1,
      "heading": "步驟標題（5字內）",
      "narration": "這個步驟的旁白（30-40字）",
      "url": "實際要開啟的網址（必填，如 https://claude.ai）",
      "action_label": "操作說明（顯示在畫面上，如：點「New Chat」→ 貼上文字）"
    }},
    {{"num": 2, "heading": "步驟標題", "narration": "旁白", "url": "https://...", "action_label": "操作說明"}},
    {{"num": 3, "heading": "步驟標題", "narration": "旁白", "url": "https://...", "action_label": "操作說明"}}
  ],
  "cta": "結尾行動呼籲（10秒，問問題+訂閱）"
}}
"""
    data  = _gemini_json(prompt)
    steps = data.get("steps", [])
    narr  = data.get("narration", "")
    title = data.get("title", topic["title"])
    desc  = data.get("description", "")
    tags  = data.get("tags", ["AI工具","Vivi AI研習社"])
    hook  = data.get("hook", "")
    cta   = data.get("cta", "")
    full_narration = f"{hook}\n{narr}\n{cta}".strip() if hook else narr
    print(f"  步驟數：{len(steps)}")
    for s in steps:
        print(f"    Step {s.get('num')}: {s.get('heading')} → {s.get('url','')}")
    return full_narration, title, desc, tags, steps

# ═══════════════════════════════════════════
# 截圖擷取（Playwright）
# ═══════════════════════════════════════════
def capture_screenshots(steps: list) -> dict:
    print("\n📸 擷取步驟截圖...")
    screenshots = {}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ⚠️ playwright 未安裝，跳過截圖")
        return screenshots
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu"]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="zh-TW",
            timezone_id="Asia/Taipei",
        )
        page = context.new_page()
        for step in steps:
            num = step.get("num")
            url = step.get("url", "")
            if not url or not url.startswith("http"):
                continue
            path = f"screenshot_step{num}.png"
            try:
                print(f"  截圖 Step {num}：{url}")
                page.goto(url, timeout=15000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                page.screenshot(path=path, full_page=False)
                screenshots[num] = path
                print(f"  ✅ 儲存：{path}")
            except Exception as e:
                print(f"  ⚠️ Step {num} 截圖失敗：{e}")
        browser.close()
    return screenshots

# ═══════════════════════════════════════════
# 語音生成（Google Cloud TTS）
# ═══════════════════════════════════════════
def generate_voice(narration: str, output: str = "voice.mp3") -> str:
    print("🎙️ 生成語音（Google Cloud TTS）...")
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={GOOGLE_TTS_KEY}"
    payload = {
        "input": {"text": narration},
        "voice": {"languageCode": "cmn-TW", "name": GOOGLE_TTS_VOICE, "ssmlGender": "FEMALE"},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": 1.05, "pitch": 1.0},
    }
    resp = _safe_post(url, headers={"Content-Type": "application/json"}, json_body=payload)
    audio_bytes = base64.b64decode(resp.json()["audioContent"])
    with open(output, "wb") as f:
        f.write(audio_bytes)
    print(f"  ✅ 語音：{output} ({Path(output).stat().st_size // 1024} KB)")
    return output

# ═══════════════════════════════════════════
# 影片渲染（16:9 教學圖卡）
# ═══════════════════════════════════════════
def render_video(audio_path: str, steps: list, screenshots: dict,
                 title: str, output: str = "video_final.mp4") -> str:
    print("🎬 渲染影片（16:9）...")
    from video_renderer import render_tutorial_video
    return render_tutorial_video(audio_path, steps, screenshots, title, output)

# ═══════════════════════════════════════════
# YouTube 上傳
# ═══════════════════════════════════════════
def upload_youtube(video_path: str, title: str, description: str, tags: list) -> str:
    print("📤 上傳 YouTube...")
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.auth.transport.requests import Request

    creds = None
    if Path("token.pickle").exists():
        with open("token.pickle", "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise EnvironmentError("YouTube token 無效，請重新授權並更新 YOUTUBE_TOKEN_B64 secret")

    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {"title": title[:100], "description": description[:5000],
                    "tags": tags, "categoryId": "28"},
        "status": {"privacyStatus": "public"},
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  上傳進度：{int(status.progress()*100)}%")
    url = f"https://youtu.be/{response['id']}"
    print(f"  ✅ 上傳完成：{url}")
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"youtube_url={url}\nvideo_title={title}\n")
    return url

# ═══════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════
def main():
    print(f"\n🚀 Vivi AI研習社 每日影片自動生產流程啟動")
    print(f"   {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} 台北時間")
    print(f"   模式：{'🔍 PREVIEW（只生成，不上傳）' if EXECUTION_MODE == 'PREVIEW' else '🚀 FULL（生成 + 上傳 YouTube）'}\n")

    manual_topic = os.getenv("MANUAL_TOPIC", "").strip()

    # ── 共同流程（PREVIEW & FULL 都執行）──
    benchmark = research_benchmark_accounts()
    topics    = analyze_viral_topics(manual_topic)
    best = topics[0] if topics else {
        "title":"3步驟用Claude整理會議記錄","keyword":"Claude 教學","score":9,"tool":"Claude"}

    print(f"\n  ⭐ 最高分選題（{best.get('score',0)}分）：{best['title']}")
    for i, t in enumerate(topics, 1):
        print(f"  {i}. [{t.get('score',0)}分] {t['title']}")

    keyword = best.get("keyword") or best["title"]
    videos  = search_youtube_videos(keyword, max_results=5)
    if videos:
        videos = analyze_video_outliers(videos, keyword)
        write_to_notion(videos, benchmark, best["title"])

    narration, title, description, tags, steps = generate_script(best)
    screenshots = capture_screenshots(steps)

    # 儲存 meta（PREVIEW 存為固定檔名，FULL 存帶時間戳）
    date_str  = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    meta_path = "video_meta.json" if EXECUTION_MODE == "PREVIEW" else f"video_meta_{date_str}.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"title":title,"description":description,"tags":tags,
                   "steps":steps,"topic":best,"reference_videos":videos,
                   "mode": EXECUTION_MODE, "generated_at": date_str},
                  f, ensure_ascii=False, indent=2)
    print(f"  📄 Meta 儲存：{meta_path}")

    audio_path = generate_voice(narration)
    video_path = render_video(audio_path, steps, screenshots, title)

    # ── 關鍵分岔點 ────────────────────────────────────
    if EXECUTION_MODE == "FULL":
        # FULL 模式：上傳 YouTube
        youtube_url = upload_youtube(video_path, title, description, tags)
        print(f"\n🎉 FULL 完成！影片已上架：{youtube_url}")
        return youtube_url
    else:
        # PREVIEW 模式：複製影片為固定檔名供 Artifact 下載，不上傳
        preview_path = "daily_preview_video.mp4"
        shutil.copy(video_path, preview_path)
        print(f"\n✅ PREVIEW 完成！")
        print(f"   📦 影片：{preview_path}（請至 GitHub Actions → Artifacts 下載確認）")
        print(f"   📋 Meta：{meta_path}")
        print(f"   📌 確認無誤後，請手動觸發 FULL 模式上傳")
        return preview_path

if __name__ == "__main__":
    main()
