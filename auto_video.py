"""
Vivi AI研習社 — 自動影片生成 & 上架 YouTube
流程：腳本文字 → ElevenLabs 語音 → 字幕卡影片 → YouTube 上傳
"""

import os
import re
import time
import textwrap
import requests
from pathlib import Path
from dotenv import load_dotenv
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import AudioFileClip, ImageClip, concatenate_videoclips
from video_renderer import render_animated_video

# 載入環境變數
load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")
HEYGEN_API_KEY = os.getenv("HEYGEN_API_KEY")
HEYGEN_AVATAR_ID = os.getenv("HEYGEN_AVATAR_ID")
YOUTUBE_CLIENT_SECRET_PATH = os.getenv("YOUTUBE_CLIENT_SECRET_PATH", "client_secret.json")

# ─────────────────────────────────────────
# 步驟 1：用 ElevenLabs 將腳本轉成語音 MP3
# ─────────────────────────────────────────
def generate_voice(script: str, output_path: str = "voice.mp3") -> str:
    print(f"🎙️  生成語音中...")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "text": script,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }
    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()

    with open(output_path, "wb") as f:
        f.write(response.content)
    print(f"✅ 語音已儲存：{output_path}")
    return output_path


# ─────────────────────────────────────────
# 步驟 2：本地生成字幕卡影片
# ─────────────────────────────────────────

# 品牌色彩設定
BG_COLOR      = (245, 240, 235)   # #f5f0eb 溫暖米色
ACCENT_COLOR  = (80,  60,  40)    # 深棕（主文字）
BRAND_COLOR   = (180, 100, 60)    # 暖橘棕（品牌名稱）
WIDTH, HEIGHT = 1080, 1920        # 9:16 Shorts 尺寸
FONT_SIZE_MAIN  = 72
FONT_SIZE_BRAND = 48
FONT_SIZE_CARD  = 68
LINE_CHARS      = 14              # 每行最多中文字數

def _load_font(size: int):
    """嘗試載入系統中文字型，找不到就用預設"""
    candidates = [
        "C:/Windows/Fonts/msjhbd.ttc",   # 微軟正黑體 Bold
        "C:/Windows/Fonts/msjh.ttc",     # 微軟正黑體
        "C:/Windows/Fonts/mingliu.ttc",  # 細明體
        "C:/Windows/Fonts/arial.ttf",    # Arial（無中文）
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()

def _wrap_text(text: str, max_chars: int) -> list[str]:
    """按標點和字數自動換行"""
    lines, current = [], ""
    for ch in text:
        current += ch
        if ch in "，。！？、：,!?:" or len(current) >= max_chars:
            lines.append(current.strip())
            current = ""
    if current.strip():
        lines.append(current.strip())
    return lines

def _make_card(lines: list[str], duration: float, brand: str = "Vivi AI研習社") -> ImageClip:
    """產生一張帶文字的靜態卡片 ImageClip"""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    font_main  = _load_font(FONT_SIZE_CARD)
    font_brand = _load_font(FONT_SIZE_BRAND)

    # 品牌名稱（頂部）
    bw = draw.textlength(brand, font=font_brand)
    draw.text(((WIDTH - bw) / 2, 120), brand, font=font_brand, fill=BRAND_COLOR)

    # 分隔線
    draw.rectangle([(160, 200), (920, 206)], fill=BRAND_COLOR)

    # 主文字（垂直置中）
    line_h = FONT_SIZE_CARD + 20
    total_h = len(lines) * line_h
    y = (HEIGHT - total_h) / 2 - 60
    for line in lines:
        lw = draw.textlength(line, font=font_main)
        draw.text(((WIDTH - lw) / 2, y), line, font=font_main, fill=ACCENT_COLOR)
        y += line_h

    # 底部裝飾
    draw.rectangle([(160, HEIGHT - 160), (920, HEIGHT - 154)], fill=BRAND_COLOR)

    return ImageClip(np.array(img)).with_duration(duration)

def _split_script_to_cards(script: str) -> list[str]:
    """將腳本依段落分成字幕卡"""
    # 按換行或句號分段
    segments = [s.strip() for s in re.split(r'\n+', script) if s.strip()]
    cards = []
    for seg in segments:
        # 超過 LINE_CHARS*3 就再切
        if len(seg) > LINE_CHARS * 3:
            parts = [seg[i:i+LINE_CHARS*2] for i in range(0, len(seg), LINE_CHARS*2)]
            cards.extend(parts)
        else:
            cards.append(seg)
    return cards

def generate_video(audio_path: str, script: str, output_path: str = "video_final.mp4") -> str:
    print("🎬 本地生成動態教學影片中...")
    return render_animated_video(audio_path, script, output_path)

def generate_video_legacy(audio_path: str, script: str, output_path: str = "video_final.mp4") -> str:
    """舊版靜態字幕卡（備用）"""
    print("🎬 本地生成字幕卡影片中（舊版）...")

    # 取得音訊時長
    audio_clip = AudioFileClip(audio_path)
    total_duration = audio_clip.duration
    print(f"  音訊時長：{total_duration:.1f} 秒")

    # 拆分腳本成字幕卡
    cards = _split_script_to_cards(script)
    n = len(cards)
    per_card = total_duration / n
    print(f"  共 {n} 張字幕卡，每張約 {per_card:.1f} 秒")

    # 為每張字幕卡建立 ImageClip
    clips = []
    for card_text in cards:
        lines = _wrap_text(card_text, LINE_CHARS)
        clip = _make_card(lines, per_card)
        clips.append(clip)

    # 合併影像 + 音訊
    video = concatenate_videoclips(clips, method="compose")
    final  = video.with_audio(audio_clip)

    print("  渲染影片（約 1-2 分鐘）...")
    final.write_videofile(
        output_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        logger=None
    )
    audio_clip.close()
    print(f"✅ 影片已儲存：{output_path}")
    return output_path


# ─────────────────────────────────────────
# 步驟 3：上傳到 YouTube
# ─────────────────────────────────────────
def upload_to_youtube(video_path: str, title: str, description: str, tags: list):
    print(f"📤 上傳到 YouTube 中...")
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    import pickle

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    token_path = "token.pickle"
    creds = None

    if Path(token_path).exists():
        with open(token_path, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            YOUTUBE_CLIENT_SECRET_PATH, SCOPES
        )
        creds = flow.run_local_server(port=0)
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "28"  # Science & Technology
        },
        "status": {
            "privacyStatus": "public"
        }
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  上傳進度：{int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"✅ 上傳完成！YouTube 連結：https://youtu.be/{video_id}")
    return f"https://youtu.be/{video_id}"


# ─────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────
def run(script: str, title: str, description: str, tags: list):
    print("\n🚀 Vivi AI研習社 自動影片流程啟動\n")
    audio = generate_voice(script)
    video = generate_video(audio, script)
    url   = upload_to_youtube(video, title, description, tags)
    print(f"\n🎉 完成！影片已上架：{url}")
    return url


# ─────────────────────────────────────────
# 主程式入口
# 用法：
#   python auto_video.py                        ← 跑預設範例腳本
#   python auto_video.py script.txt             ← 從 txt 讀腳本（同目錄下需有 meta.txt 含 title/desc/tags）
#   python auto_video.py --upload-only          ← 只上傳已有的 video_final.mp4
# ─────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import json

    # ── 預設腳本（選題一：Claude Code 副業）──
    DEFAULT_SCRIPT = """
我文科出身、沒學過程式，但上週我用 Claude Code，20 分鐘就做出了一個自動整理資料的工具，現在每天幫我省 2 小時。

你是不是也覺得 AI 很厲害，但不知道怎麼真的用在自己的工作上？

我來教你我的實際做法，三步驟，今天就能試：

第一步：打開 claude.ai，切換到「Claude Code」模式。不用安裝任何東西，直接在網頁用。

第二步：用中文描述你想要的功能。我當時輸入的是：「幫我把這份 Excel 的客戶資料，依縣市分類，每個縣市存成一個獨立檔案。」就這樣一句話。

第三步：Claude 會自動寫好程式並執行。你只要按「Run」，結果直接出來。我第一次用的時候，還以為自己按錯了，因為真的太快了。

我用這個方法做了一個每週自動整理報表的工具，現在同事都在問我怎麼做的。

你最想用 AI 自動化哪件事？留言告訴我，我來幫你想怎麼做。

我是 Vivi，非工科出身的 PM，每週分享真正用得到的 AI 實作。記得訂閱，下週見。
""".strip()

    DEFAULT_TITLE = "非工程師也能用！我用 Claude Code 做出第一個 AI 副業產品"
    DEFAULT_DESC  = """
我文科出身、沒學過程式，但用 Claude Code 2 小時就做出了可以賺錢的工具！

這支影片教你：
✅ Claude Code 是什麼
✅ 非工科也能用的步驟
✅ 如何把成果變成副業收入

👇 完整教學連結在下方
#AI副業 #ClaudeCode #AI工具 #職場效率 #非工程師
""".strip()
    DEFAULT_TAGS  = ["AI副業", "Claude Code", "AI工具", "職場效率", "非工程師", "台灣", "Vivi AI研習社"]

    args = sys.argv[1:]

    # ── 模式 1：只上傳 ──
    if "--upload-only" in args:
        if not Path("video_final.mp4").exists():
            print("❌ 找不到 video_final.mp4，請先生成影片")
            sys.exit(1)
        print("\n📤 直接上傳 video_final.mp4\n")
        url = upload_to_youtube("video_final.mp4", DEFAULT_TITLE, DEFAULT_DESC, DEFAULT_TAGS)
        print(f"\n🎉 完成！{url}")

    # ── 模式 2：從 JSON 檔讀取腳本與 meta ──
    elif args and Path(args[0]).exists():
        meta_path = Path(args[0])
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        SCRIPT = meta["script"]
        TITLE  = meta["title"]
        DESC   = meta["description"]
        TAGS   = meta["tags"]
        print(f"\n📋 讀取腳本：{meta_path.name}")
        # 清除舊檔，強制重新生成
        for f in ["voice.mp3", "video_final.mp4"]:
            if Path(f).exists(): Path(f).unlink()
        run(script=SCRIPT, title=TITLE, description=DESC, tags=TAGS)

    # ── 模式 3：預設（找到現有影片就直接上傳）──
    else:
        if Path("video_final.mp4").exists():
            print("\n🚀 找到已生成的影片，直接上傳 YouTube\n")
            url = upload_to_youtube("video_final.mp4", DEFAULT_TITLE, DEFAULT_DESC, DEFAULT_TAGS)
            print(f"\n🎉 完成！影片已上架：{url}")
        else:
            run(script=DEFAULT_SCRIPT, title=DEFAULT_TITLE, description=DEFAULT_DESC, tags=DEFAULT_TAGS)
