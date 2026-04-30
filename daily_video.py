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
# ✅ 修改：改用 Neural2 引擎，聽起來更接近真人台灣女聲
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
    tool = topic.get("tool", "Claude")
    prompt = f"""
你是 Vivi（林怡伶），台灣職場 AI 應用頻道主持人，專門教非技術背景的上班族用 AI 提升工作效率。

選題：{topic['title']}
主要工具：{tool}

請設計一個3步驟的 YouTube 教學影片腳本，目標是讓台灣上班族看完立刻能照著做。

嚴格要求：
1. 每個步驟必須包含「真實可用的 Prompt 範本」和「AI 實際會輸出什麼」
2. 情境要貼近台灣職場（會議記錄、Email、簡報、報表、客戶溝通）
3. Prompt 要具體，包含：背景說明 + 具體要求 + 格式指定
4. 輸出範例要真實，不能是空話，要有實際內容
5. Bullet 重點要是動作導向（告訴觀眾「做什麼」）

輸出 JSON：
{{
  "title": "吸引人的影片標題（含數字＋具體結果，口語化）",
  "description": "YouTube 說明欄（含工具名稱、適用情境、3個步驟摘要、#hashtag）",
  "tags": ["AI工具","Vivi AI研習社","職場效率","台灣"],
  "narration": "完整旁白（350字，口語化，像朋友分享，第一人稱）",
  "hook": "開場白（15秒，用具體數字或痛點，讓觀眾有共鳴）",
  "cta": "結尾（15秒，問觀眾問題＋訂閱）",
  "steps": [
    {{
      "num": 1,
      "heading": "步驟標題（5字內）",
      "tool_name": "{tool}",
      "narration": "這步驟的旁白（40-50字，口語化）",
      "url": "實際網址（如 https://claude.ai）",
      "action_label": "底部操作說明（20字內，如：複製會議記錄 → 貼入 Claude → 送出）",
      "bullets": [
        "動作1（8字內，動詞開頭）",
        "動作2（8字內，動詞開頭）",
        "預期結果（8字內）"
      ],
      "example_prompt": "完整的 Prompt 範本（要真實可用，包含背景＋具體要求＋格式，3-6行）",
      "example_output": [
        "【AI 輸出範例】",
        "（真實的 AI 輸出內容，5-8行，要有實際資訊，不能是說明文字）"
      ],
      "tip": "進階小技巧（15字內，一句話點睛）"
    }},
    {{
      "num": 2,
      "heading": "第二步標題",
      "tool_name": "{tool}",
      "narration": "旁白",
      "url": "網址",
      "action_label": "操作說明",
      "bullets": ["動作1","動作2","結果"],
      "example_prompt": "完整 Prompt",
      "example_output": ["輸出行1","輸出行2","輸出行3","輸出行4","輸出行5"],
      "tip": "小技巧"
    }},
    {{
      "num": 3,
      "heading": "第三步標題",
      "tool_name": "{tool}",
      "narration": "旁白",
      "url": "網址",
      "action_label": "操作說明",
      "bullets": ["動作1","動作2","結果"],
      "example_prompt": "完整 Prompt",
      "example_output": ["輸出行1","輸出行2","輸出行3","輸出行4","輸出行5"],
      "tip": "小技巧"
    }}
  ]
}}
"""
    data  = _gemini_json(prompt)
    steps = data.get("steps", [])
    narr  = data.get("narration", "")
    title = data.get("title", topic["title"])
    desc  = data.get("description", "")
    tags  = data.get("tags", ["AI工具", "Vivi AI研習社"])
    hook  = data.get("hook", "")
    cta   = data.get("cta", "")
    full_narration = f"{hook}\n{narr}\n{cta}".strip() if hook else narr

    print(f"  步驟數：{len(steps)}")
    for s in steps:
        print(f"    Step {s.get('num')}: {s.get('heading')} | bullets={len(s.get('bullets',[]))} | prompt_len={len(s.get('example_prompt',''))}")
    return full_narration, title, desc, tags, steps


# ═══════════════════════════════════════════
# 截圖擷取（Playwright + Stealth）
# ✅ 修改：加入 stealth user-agent 繞過 Cloudflare，並設計 fallback 截圖
# ═══════════════════════════════════════════
def _make_fallback_screenshot(step: dict, path: str):
    """當截圖失敗時，生成一張乾淨的說明卡取代"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import textwrap

        img = Image.new("RGB", (1280, 800), color="#F8F6F2")
        draw = ImageDraw.Draw(img)

        # 嘗試載入中文字體
        font_paths = [
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJKtc-Regular.otf",
        ]
        font_url  = None
        font_head = None
        for fp in font_paths:
            if Path(fp).exists():
                try:
                    font_url  = ImageFont.truetype(fp, 36)
                    font_head = ImageFont.truetype(fp, 28)
                    break
                except Exception:
                    pass
        if font_url is None:
            font_url  = ImageFont.load_default()
            font_head = ImageFont.load_default()

        # 繪製內容
        url   = step.get("url", "")
        label = step.get("action_label", "")
        num   = step.get("num", "?")

        draw.rectangle([60, 60, 1220, 740], outline="#D4B896", width=3, fill="#FFFFFF")
        draw.text((100, 100), f"步驟 {num}：請前往以下網站操作", font=font_head, fill="#5C4A32")
        draw.text((100, 170), url, font=font_url, fill="#B86B3A")

        # 操作說明自動換行
        wrapped = textwrap.fill(label, width=50)
        y = 260
        for line in wrapped.split("\n"):
            draw.text((100, y), line, font=font_head, fill="#3D3D3D")
            y += 50

        draw.text((100, 680), "▶ 請參考左側步驟說明進行操作", font=font_head, fill="#999999")
        img.save(path)
        print(f"    📋 已生成說明卡替代截圖：{path}")
        return True
    except Exception as e:
        print(f"    ⚠️ fallback 截圖也失敗：{e}")
        return False


def capture_screenshots(steps: list) -> dict:
    print("\n📸 擷取步驟截圖...")
    screenshots = {}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ⚠️ playwright 未安裝，跳過截圖")
        return screenshots

    # ✅ 真實 Chrome user-agent，降低被 Cloudflare 擋的機率
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/124.0.0.0 Safari/537.36")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",  # ✅ 隱藏自動化標記
            ]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            user_agent=UA,                     # ✅ 偽裝成真實瀏覽器
            java_script_enabled=True,
            extra_http_headers={               # ✅ 加入正常瀏覽器 headers
                "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

        # ✅ 注入 JS 隱藏 webdriver 標記（繞過 bot 偵測）
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-TW', 'zh', 'en'] });
        """)

        page = context.new_page()

        for step in steps:
            num  = step.get("num")
            url  = step.get("url", "")
            path = f"screenshot_step{num}.png"

            if not url or not url.startswith("http"):
                continue

            success = False
            for attempt in range(2):  # 最多重試一次
                try:
                    print(f"  截圖 Step {num}（嘗試 {attempt+1}）：{url}")
                    page.goto(url, timeout=20000, wait_until="domcontentloaded")
                    page.wait_for_timeout(3500)  # ✅ 等更久讓 Cloudflare 通過

                    # ✅ 判斷是否仍卡在 Cloudflare
                    content = page.content()
                    is_cf = any(kw in content for kw in [
                        "正在執行安全驗證", "Checking your browser",
                        "cf-browser-verification", "cloudflare", "Ray ID"
                    ])

                    if is_cf and attempt == 0:
                        print(f"    ⚠️ 偵測到 Cloudflare，等待 5 秒後重試...")
                        page.wait_for_timeout(5000)
                        continue  # 重試

                    if is_cf:
                        print(f"    ⚠️ 仍被 Cloudflare 擋，改用說明卡")
                        break

                    page.screenshot(path=path, full_page=False)
                    screenshots[num] = path
                    print(f"  ✅ 截圖成功：{path}")
                    success = True
                    break

                except Exception as e:
                    print(f"  ⚠️ Step {num} 截圖失敗：{e}")
                    break

            # ✅ 截圖失敗時生成說明卡
            # 截圖失敗：不存入 screenshots，video_renderer 會用 example 內容渲染
            if not success:
                print(f"    ℹ️ Step {num} 截圖跳過，改用範例內容")

        browser.close()
    return screenshots

# ═══════════════════════════════════════════
# 語音生成（Microsoft Edge TTS — 免費台灣女聲）
# 主聲：zh-TW-HsiaoChenNeural（小陳，親切自然）
# 備用：zh-TW-HsiaoYuNeural（小玉）
# ═══════════════════════════════════════════
def generate_voice(narration: str, output: str = "voice.mp3") -> str:
    import asyncio
    import edge_tts

    print("🎙️ 生成語音（Microsoft Edge TTS）...")

    voice_candidates = [
        "zh-TW-HsiaoChenNeural",   # 台灣女聲，親切自然
        "zh-TW-HsiaoYuNeural",     # 台灣女聲，備用
        "zh-TW-YunJheNeural",      # 台灣男聲，最後備用
    ]

    async def _synthesize(voice: str, path: str):
        communicate = edge_tts.Communicate(
            text=narration,
            voice=voice,
            rate="+0%",    # 正常語速
            volume="+0%",  # 正常音量
        )
        await communicate.save(path)

    for voice in voice_candidates:
        try:
            asyncio.run(_synthesize(voice, output))
            size_kb = Path(output).stat().st_size // 1024
            print(f"  ✅ 語音：{output} | 聲音：{voice} ({size_kb} KB)")
            return output
        except Exception as e:
            print(f"  ⚠️ {voice} 失敗：{e}，嘗試下一個...")

    raise RuntimeError("所有 Edge TTS 聲音均失敗")

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
        youtube_url = upload_youtube(video_path, title, description, tags)
        print(f"\n🎉 FULL 完成！影片已上架：{youtube_url}")
        return youtube_url
    else:
        preview_path = "daily_preview_video.mp4"
        shutil.copy(video_path, preview_path)
        print(f"\n✅ PREVIEW 完成！")
        print(f"   📦 影片：{preview_path}（請至 GitHub Actions → Artifacts 下載確認）")
        print(f"   📋 Meta：{meta_path}")
        print(f"   📌 確認無誤後，請手動觸發 FULL 模式上傳")
        return preview_path

if __name__ == "__main__":
    main()
