"""
video_renderer.py — Vivi AI研習社 動畫字幕影片渲染器

功能：
- 將腳本切分為字幕卡
- 每張卡淡入淡出動畫
- 品牌色配置（BG 米白 / 品牌橘棕 / 文字深棕）
- 支援 CJK 字體（Linux / Windows 自動偵測）
- 輸出 1080x1920 垂直影片（適合 YouTube Shorts）
"""

from __future__ import annotations
import re
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from moviepy import AudioFileClip, ImageClip, concatenate_videoclips

# ── 品牌視覺 ────────────────────────────────────────────────────────────

BG_COLOR      = (245, 240, 235)
ACCENT_COLOR  = (80,  60,  40)
BRAND_COLOR   = (180, 100, 60)
FADE_COLOR    = (245, 240, 235)   # 淡入淡出用（與背景同色）
WIDTH, HEIGHT = 1080, 1920
BRAND_NAME    = "Vivi AI研習社"

# 每張卡的字元上限（根據字體大小調整）
MAX_CHARS_PER_LINE = 13
MAX_LINES_PER_CARD = 4

# 淡入淡出秒數
FADE_DURATION = 0.25


# ── 字體載入 ────────────────────────────────────────────────────────────

def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        # Linux（GitHub Actions / Ubuntu）
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJKtc-Regular.otf",
        # Windows
        "C:/Windows/Fonts/msjhbd.ttc",
        "C:/Windows/Fonts/msjh.ttc",
        "C:/Windows/Fonts/mingliu.ttc",
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Arial Unicode MS.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    print(f"  ⚠️ 找不到 CJK 字體，使用預設字體（中文可能無法顯示）")
    return ImageFont.load_default()


# ── 文字斷行 ────────────────────────────────────────────────────────────

def _split_to_lines(text: str, max_chars: int = MAX_CHARS_PER_LINE) -> list[str]:
    """將一段文字依標點 / 長度切成多行。"""
    lines: list[str] = []
    current = ""
    for ch in text:
        current += ch
        # 遇到標點或達到上限就斷行
        if ch in "，。！？、：；,!?:;" or len(current) >= max_chars:
            lines.append(current.strip())
            current = ""
    if current.strip():
        lines.append(current.strip())
    return [l for l in lines if l]


def _split_script_to_cards(script: str) -> list[list[str]]:
    """將完整腳本切成多張字幕卡，每卡最多 MAX_LINES_PER_CARD 行。"""
    # 先依句子分割（以句末標點為界）
    sentences = re.split(r'(?<=[。！？\n])', script)
    sentences = [s.strip() for s in sentences if s.strip()]

    cards: list[list[str]] = []
    buffer: list[str] = []

    for sentence in sentences:
        lines = _split_to_lines(sentence)
        for line in lines:
            buffer.append(line)
            if len(buffer) >= MAX_LINES_PER_CARD:
                cards.append(buffer)
                buffer = []

    if buffer:
        cards.append(buffer)

    return cards


# ── 單張字幕卡（靜態 PIL Image）────────────────────────────────────────

def _make_card_image(lines: list[str]) -> np.ndarray:
    img  = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    f_brand = _load_font(52)
    f_text  = _load_font(76)

    # 品牌名稱（置中，頂部）
    bw = draw.textlength(BRAND_NAME, font=f_brand)
    draw.text(((WIDTH - bw) / 2, 110), BRAND_NAME, font=f_brand, fill=BRAND_COLOR)

    # 品牌線（品牌名下方）
    draw.rectangle([(120, 205), (960, 212)], fill=BRAND_COLOR)

    # 字幕文字（垂直置中）
    line_height = 102
    total_h     = len(lines) * line_height
    y           = (HEIGHT - total_h) / 2 - 40

    for line in lines:
        lw = draw.textlength(line, font=f_text)
        draw.text(((WIDTH - lw) / 2, y), line, font=f_text, fill=ACCENT_COLOR)
        y += line_height

    # 底部裝飾線
    draw.rectangle([(120, HEIGHT - 170), (960, HEIGHT - 163)], fill=BRAND_COLOR)

    return np.array(img)


# ── 淡入淡出效果 ────────────────────────────────────────────────────────

def _fade_frame(base: np.ndarray, t: float, duration: float,
                fade_in: bool = True) -> np.ndarray:
    """對單一幀套用淡入或淡出，回傳合成後的 numpy array。"""
    alpha = (t / FADE_DURATION) if fade_in else (1.0 - t / FADE_DURATION)
    alpha = float(np.clip(alpha, 0.0, 1.0))
    bg    = np.full_like(base, FADE_COLOR, dtype=np.float32)
    blended = alpha * base.astype(np.float32) + (1 - alpha) * bg
    return blended.astype(np.uint8)


def _make_clip_with_fade(lines: list[str], duration: float) -> ImageClip:
    """回傳帶淡入淡出的 ImageClip。"""
    base = _make_card_image(lines)

    def make_frame(t: float) -> np.ndarray:
        if t < FADE_DURATION:
            return _fade_frame(base, t, FADE_DURATION, fade_in=True)
        elif t > duration - FADE_DURATION:
            return _fade_frame(base, duration - t, FADE_DURATION, fade_in=False)
        return base

    clip = ImageClip(make_frame, duration=duration)
    return clip


# ── 主渲染函式 ──────────────────────────────────────────────────────────

def render_animated_video(
    audio_path: str,
    script: str,
    output: str = "video_final.mp4",
) -> str:
    """
    根據音頻時長 + 腳本，渲染帶動畫字幕的垂直短影片。

    Args:
        audio_path: ElevenLabs 產生的 .mp3 路徑
        script:     完整腳本文字
        output:     輸出 .mp4 路徑

    Returns:
        output 路徑
    """
    print(f"  載入音頻：{audio_path}")
    audio     = AudioFileClip(audio_path)
    total_dur = audio.duration
    print(f"  音頻時長：{total_dur:.1f} 秒")

    # 切割腳本為字幕卡
    cards = _split_script_to_cards(script)
    if not cards:
        cards = [["Vivi AI研習社", "AI 工具教學"]]

    # 每張卡平均分配時間
    card_dur = total_dur / len(cards)
    print(f"  字幕卡數：{len(cards)} 張，每張 {card_dur:.1f} 秒")

    clips = [_make_clip_with_fade(card, card_dur) for card in cards]
    video = concatenate_videoclips(clips, method="compose")

    # 合併音頻
    video = video.with_audio(audio)

    # 輸出
    print(f"  渲染輸出：{output}")
    video.write_videofile(
        output,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        preset="fast",
        logger=None,          # 靜音 moviepy 內部 log
    )

    print(f"  ✅ 影片完成：{output} ({Path(output).stat().st_size // (1024*1024)} MB)")
    return output
