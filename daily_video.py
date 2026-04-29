"""
Vivi AI研習社 — 每日影片自動生產流程
任務一：搜尋英/日對標帳號
任務二：爆款選題分析與評分
任務三：YouTube 參考影片搜尋 + 寫入 Notion
+ 腳本生成 → 語音 → 影片渲染 → YouTube 上傳
"""

import os, re, json, datetime, base64, time, numpy as np
from pathlib import Path
import requests
import google.generativeai as genai
from PIL import Image, ImageDraw, ImageFont
from moviepy import AudioFileClip, ImageClip, concatenate_videoclips
from video_renderer import render_animated_video

# ── 環境變數 ──────────────────────────────

GEMINI_KEY       = os.getenv("GEMINI_API_KEY", "")
ELEVENLABS_KEY   = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE = os.getenv("ELEVENLABS_VOICE_ID", "oGcfKz3pBlkD56OfrAe5")
YOUTUBE_API_KEY  = os.getenv("YOUTUBE_API_KEY", "")
NOTION_TOKEN     = os.getenv("NOTION_TOKEN", "")
NOTION_VIDEO_DB  = os.getenv("NOTION_VIDEO_DB", "")

# ── Gemini 初始化 ─────────────────────────
genai.configure(api_key=GEMINI_KEY)
gemini = genai.GenerativeModel("gemini-1.5-flash")


# ── 品牌視覺設定 ──────────────────────────

BG_COLOR     = (245, 240, 235)
ACCENT_COLOR = (80,  60,  40)
BRAND_COLOR  = (180, 100, 60)
WIDTH, HEIGHT = 1080, 1920
LINE_CHARS    = 14

# ═══════════════════════════════════════════
# 任務一：對標帳號研究
# ═══════════════════════════════════════════

def research_benchmark_accounts() -> dict:
    print("\n🔍 任務一：搜尋對標帳號...")

    prompt = """
你是 Vivi AI研習社的內容策略師。Vivi 是台灣非工科出身的職場 PM，
YouTube 頻道定位：AI 工具教學 × 職場效率 × 普通人也能用。

請列出 AI 工具教學 & AI 變現領域的對標帳號：

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
    msg = gemini.generate_content(prompt)
    text = msg.text
    try:
        json_match = re.search(r'\{[\s\S]+\}', text)
        return json.loads(json_match.group()) if json_match else {"english": [], "japanese": [], "raw": text}
    except Exception:
        return {"english": [], "japanese": [], "raw": text}


# ═══════════════════════════════════════════
# 任務二：爆款選題分析
# ═══════════════════════════════════════════

def analyze_viral_topics(manual_topic: str = "") -> list:
    print("\n💡 任務二：爆款選題分析...")

    if manual_topic:
        print(f"  使用指定選題：{manual_topic}")
        return [{"title": manual_topic, "score": 10, "keyword": manual_topic, "appeal": "用戶指定", "algorithm": "手動選題"}]

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

輸出 JSON：
[
  {
    "title": "...",
    "appeal": "...",
    "algorithm": "...",
    "keyword": "...",
    "score": 9,
    "reason": "..."
  },
  ...
]
"""
    msg = claude.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text
    try:
        json_match = re.search(r'\[[\s\S]+\]', text)
        topics = json.loads(json_match.group()) if json_match else []
        topics.sort(key=lambda x: x.get("score", 0), reverse=True)
        return topics
    except Exception:
        return [{"title": "非工程師用 AI 做出副業的完整流程", "score": 9,
                 "keyword": "AI副業 非工程師", "appeal": "貼近大眾痛點", "algorithm": "搜尋量高"}]


# ═══════════════════════════════════════════
# 任務三：YouTube 參考影片搜尋
# ═══════════════════════════════════════════

def search_youtube_videos(keyword: str, max_results: int = 5) -> list:
    print(f"\n🎥 搜尋 YouTube 參考影片：{keyword}")
    if not YOUTUBE_API_KEY:
        print("  ⚠️ 未設定 YOUTUBE_API_KEY，跳過搜尋")
        return []

    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": keyword,
        "type": "video",
        "order": "viewCount",
        "maxResults": max_results * 2,
        "regionCode": "TW",
        "relevanceLanguage": "zh-Hant",
        "key": YOUTUBE_API_KEY
    }
    resp = requests.get(url, params=params)
    items = resp.json().get("items", [])

    # 取得播放量
    video_ids = ",".join([i["id"]["videoId"] for i in items])
    stats_resp = requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={"part": "statistics,snippet", "id": video_ids, "key": YOUTUBE_API_KEY}
    )
    stats_map = {v["id"]: v for v in stats_resp.json().get("items", [])}

    videos = []
    for item in items[:max_results]:
        vid_id = item["id"]["videoId"]
        stat = stats_map.get(vid_id, {})
        stats = stat.get("statistics", {})
        snippet = stat.get("snippet", item.get("snippet", {}))
        view_count = int(stats.get("viewCount", 0))
        videos.append({
            "title":        snippet.get("title", ""),
            "channel":      snippet.get("channelTitle", ""),
            "views":        view_count,
            "published_at": snippet.get("publishedAt", "")[:10],
            "url":          f"https://www.youtube.com/watch?v={vid_id}",
            "video_id":     vid_id,
        })

    return sorted(videos, key=lambda x: x["views"], reverse=True)


def analyze_video_outliers(videos: list, keyword: str) -> list:
    """用 Claude 分析每部影片的異常值"""
    print("  🤖 分析影片異常值...")
    if not videos:
        return videos

    video_summary = json.dumps([
        {"title": v["title"], "channel": v["channel"], "views": v["views"], "date": v["published_at"]}
        for v in videos
    ], ensure_ascii=False)

    prompt = f"""
以下是 YouTube 關鍵字「{keyword}」的熱門影片，請分析每部影片播放量為何特別高。

{video_summary}

對每部影片，以 1-2 句話說明異常值原因，例如：
- 標題用了恐懼感或好奇心缺口
- 發布時機剛好在某個新聞熱點之後
- 是第一個報導某個新功能
- 縮圖設計特別吸睛
- 頻道本身有大量忠實訂閱者

輸出 JSON 陣列，每個元素只有 "title" 和 "outlier_reason" 兩個 key。
"""
    msg = claude.messages.create(
        model="claude-opus-4-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text
    try:
        json_match = re.search(r'\[[\s\S]+\]', text)
        analyses = json.loads(json_match.group()) if json_match else []
        analysis_map = {a["title"]: a.get("outlier_reason", "") for a in analyses}
        for v in videos:
            v["outlier_reason"] = analysis_map.get(v["title"], "")
    except Exception:
        pass
    return videos


# ═══════════════════════════════════════════
# 寫入 Notion
# ═══════════════════════════════════════════

def write_to_notion(videos: list, benchmark: dict, topic_title: str):
    print("\n📝 寫入 Notion...")
    if not NOTION_TOKEN or not NOTION_VIDEO_DB:
        print("  ⚠️ 未設定 NOTION_TOKEN 或 NOTION_VIDEO_DB，跳過")
        return

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }

    for v in videos:
        views_str = f"{v['views']:,}" if v['views'] else "N/A"
        page = {
            "parent": {"database_id": NOTION_VIDEO_DB},
            "properties": {
                "影片標題": {"title": [{"text": {"content": v["title"]}}]},
                "博主名稱": {"rich_text": [{"text": {"content": v["channel"]}}]},
                "播放量":   {"rich_text": [{"text": {"content": views_str}}]},
                "上傳日期": {"rich_text": [{"text": {"content": v["published_at"]}}]},
                "影片連結": {"url": v["url"]},
                "異常值分析": {"rich_text": [{"text": {"content": v.get("outlier_reason", "")}}]},
                "對應選題": {"rich_text": [{"text": {"content": topic_title}}]},
            }
        }
        resp = requests.post("https://api.notion.com/v1/pages", headers=headers, json=page)
        if resp.status_code == 200:
            print(f"  ✅ 寫入：{v['title'][:40]}")
        else:
            print(f"  ❌ 失敗：{resp.status_code} {resp.text[:100]}")


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
   例：「我昨天用 Claude，20 分鐘整理完 3 個月的會議記錄」
2. 共鳴（5秒）：點出觀眾的痛點，一句話就好
3. 實際步驟（35秒）：3 個具體可操作的步驟，每步驟要說：
   - 去哪個工具 / 打開哪個畫面
   - 輸入什麼指令或做什麼動作
   - 會得到什麼結果
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
    msg = claude.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text
    try:
        json_match = re.search(r'\{[\s\S]+\}', text)
        data = json.loads(json_match.group()) if json_match else {}
        return (
            data.get("script", text),
            data.get("title", topic["title"]),
            data.get("description", ""),
            data.get("tags", ["AI工具", "Vivi AI研習社"])
        )
    except Exception:
        return text, topic["title"], "", ["AI工具", "Vivi AI研習社"]


# ═══════════════════════════════════════════
# 語音生成（ElevenLabs）
# ═══════════════════════════════════════════

def generate_voice(script: str, output: str = "voice.mp3") -> str:
    print("🎙️  生成語音（ElevenLabs）...")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE}"
    headers = {"xi-api-key": ELEVENLABS_KEY, "Content-Type": "application/json"}
    payload = {
        "text": script,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
    }
    resp = requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    with open(output, "wb") as f:
        f.write(resp.content)
    print(f"  ✅ 語音儲存：{output} ({Path(output).stat().st_size // 1024} KB)")
    return output


# ═══════════════════════════════════════════
# 影片渲染（字幕卡）
# ═══════════════════════════════════════════

def _load_font(size: int):
    for path in [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",  # Linux (GitHub Actions)
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/msjhbd.ttc",   # Windows
        "C:/Windows/Fonts/msjh.ttc",
    ]:
        if Path(path).exists():
            try: return ImageFont.truetype(path, size)
            except: continue
    return ImageFont.load_default()

def _wrap(text: str, max_chars: int) -> list:
    lines, cur = [], ""
    for ch in text:
        cur += ch
        if ch in "，。！？、：,!?:" or len(cur) >= max_chars:
            lines.append(cur.strip())
            cur = ""
    if cur.strip(): lines.append(cur.strip())
    return lines

def _make_card(lines: list, duration: float) -> ImageClip:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    f72 = _load_font(72); f48 = _load_font(48)
    brand = "Vivi AI研習社"
    bw = draw.textlength(brand, font=f48)
    draw.text(((WIDTH-bw)/2, 120), brand, font=f48, fill=BRAND_COLOR)
    draw.rectangle([(160, 210), (920, 216)], fill=BRAND_COLOR)
    lh = 94; th = len(lines) * lh
    y = (HEIGHT - th) / 2 - 60
    for line in lines:
        lw = draw.textlength(line, font=f72)
        draw.text(((WIDTH-lw)/2, y), line, font=f72, fill=ACCENT_COLOR)
        y += lh
    draw.rectangle([(160, HEIGHT-160), (920, HEIGHT-154)], fill=BRAND_COLOR)
    return ImageClip(np.array(img)).with_duration(duration)

def render_video(audio_path: str, script: str, output: str = "video_final.mp4") -> str:
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
    import pickle

    creds = None
    if Path("token.pickle").exists():
        with open("token.pickle", "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        # 在 GitHub Actions 環境無法互動，嘗試 refresh
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        else:
            raise Exception("YouTube token 無效，請重新授權後更新 YOUTUBE_TOKEN_B64 secret")

    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {"title": title, "description": description, "tags": tags, "categoryId": "28"},
        "status":  {"privacyStatus": "public"}
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part=",".join(body.keys()), body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  上傳進度：{int(status.progress() * 100)}%")

    url = f"https://youtu.be/{response['id']}"
    print(f"  ✅ 上傳完成：{url}")
    return url


# ═══════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════

def main():
    print("\n🚀 Vivi AI研習社 每日影片自動生產流程啟動")
    print(f"   {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} 台北時間\n")

    manual_topic = os.getenv("MANUAL_TOPIC", "").strip()

    # 任務一：對標帳號研究
    benchmark = research_benchmark_accounts()
    print(f"  找到英文帳號：{len(benchmark.get('english', []))} 個")
    print(f"  找到日文帳號：{len(benchmark.get('japanese', []))} 個")

    # 任務二：選題分析
    topics = analyze_viral_topics(manual_topic)
    best = topics[0] if topics else {"title": "AI 工具入門", "keyword": "AI工具", "score": 8}
    print(f"\n  ⭐ 最高分選題（{best.get('score',0)} 分）：{best['title']}")

    # 列出所有選題
    for i, t in enumerate(topics, 1):
        print(f"  {i}. [{t.get('score',0)}分] {t['title']}")

    # 任務三：YouTube 搜尋 + Notion 寫入
    keyword = best.get("keyword", best["title"])
    videos = search_youtube_videos(keyword, max_results=5)
    if videos:
        videos = analyze_video_outliers(videos, keyword)
        write_to_notion(videos, benchmark, best["title"])

    # 生成腳本
    script, title, description, tags = generate_script(best)

    # 儲存 meta
    meta = {"title": title, "description": description, "tags": tags,
            "topic": best, "benchmark": benchmark, "reference_videos": videos}
    with open("video_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

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
