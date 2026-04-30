"""
video_renderer.py — Vivi AI研習社 16:9 教學影片渲染器

格式：1920x1080 (16:9) YouTube 標準
布局：
  - Hook 卡：全寬置中大字
  - 步驟卡：左側文字(40%) + 右側截圖(60%)
  - CTA 卡：全寬置中大字
"""

from __future__ import annotations
import re, textwrap
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import AudioFileClip, VideoClip, ImageClip, concatenate_videoclips

# ── 尺寸與配色 ───────────────────────────────────────────────────────────

W, H          = 1920, 1080       # 16:9
TOP_BAR       = 80               # 頂部品牌列高度
BOT_BAR       = 80               # 底部操作說明列高度
CONTENT_TOP   = TOP_BAR + 10
CONTENT_BOT   = H - BOT_BAR - 10
CONTENT_H     = CONTENT_BOT - CONTENT_TOP

LEFT_W        = 740              # 左側文字區寬度
DIVIDER_X     = 760
RIGHT_X       = 780              # 右側截圖起始 X
RIGHT_W       = W - RIGHT_X - 20

BG            = (245, 242, 238)
BRAND_BG      = (50,  40,  30)
BRAND_TEXT    = (220, 180, 100)
STEP_BG       = (235, 228, 218)
NUM_BG        = (180, 100, 60)
NUM_TEXT      = (255, 255, 255)
HEADING_COL   = (50,  40,  30)
BODY_COL      = (80,  65,  50)
ACTION_BG     = (60,  50,  40)
ACTION_TEXT   = (200, 180, 140)
DIVIDER_COL   = (180, 100, 60)
FADE_BG       = BG
FADE_DUR      = 0.2

BRAND_NAME    = "Vivi AI研習社"


# ── 字體 ─────────────────────────────────────────────────────────────────

def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJKtc-Regular.otf",
        "C:/Windows/Fonts/msjhbd.ttc",
        "C:/Windows/Fonts/msjh.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()

def _font_bold(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "C:/Windows/Fonts/msjhbd.ttc",
    ]:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return _font(size)


# ── 截圖載入與處理 ────────────────────────────────────────────────────────

def _load_screenshot(path: str | None, target_w: int, target_h: int) -> Image.Image | None:
    """載入截圖並縮放填滿 target area，失敗則回傳 None。"""
    if not path or not Path(path).exists():
        return None
    try:
        img = Image.open(path).convert("RGB")
        # 等比例縮放，填滿 target（crop 多餘部分）
        ratio_w = target_w / img.width
        ratio_h = target_h / img.height
        ratio   = max(ratio_w, ratio_h)
        new_w   = int(img.width  * ratio)
        new_h   = int(img.height * ratio)
        img     = img.resize((new_w, new_h), Image.LANCZOS)
        # 置中裁切
        left = (new_w - target_w) // 2
        top  = (new_h - target_h) // 2
        img  = img.crop((left, top, left + target_w, top + target_h))
        return img
    except Exception as e:
        print(f"  ⚠️ 截圖載入失敗 {path}：{e}")
        return None


def _placeholder(target_w: int, target_h: int, text: str = "",
                 url: str = "", action_label: str = "") -> Image.Image:
    """仿真瀏覽器 UI — 當真實截圖被防火牆擋時顯示"""
    img  = Image.new("RGB", (target_w, target_h), "#F5F3EF")
    draw = ImageDraw.Draw(img)
    f_sm  = _font(20)
    f_md  = _font(26)
    f_lg  = _font_bold(32)
    f_url = _font(22)
    # ── 瀏覽器 chrome ──
    draw.rectangle([0, 0, target_w, target_h], fill="#ECEAE5")
    draw.rectangle([0, 0, target_w, 48], fill="#D0CCC6")
    for cx, col in [(16,"#FF5F57"),(36,"#FEBC2E"),(56,"#28C840")]:
        draw.ellipse([cx-7,17,cx+7,31], fill=col)
    bar_url = url or "claude.ai"
    draw.rectangle([80, 10, target_w-16, 38], fill="white", outline="#BBBBBB", width=1)
    draw.text((94, 16), bar_url[:60], font=f_url, fill="#555555")
    # ── 主內容 ──
    draw.rectangle([0, 48, target_w, target_h], fill="white")
    if "claude" in (url or "").lower():
        draw.rectangle([0, 48, 200, target_h], fill="#F7F4EF")
        draw.text((14, 64),  "✦ Claude", font=_font_bold(26), fill="#8B5E3C")
        draw.text((14, 102), "+ 新對話",  font=f_sm, fill="#7A6A58")
        draw.rectangle([4, 130, 196, 168], fill="#EDE9E3")
        draw.text((14, 138), "今天的對話", font=f_sm, fill="#5C4A32")
        draw.rectangle([210, 48, target_w, target_h], fill="white")
        draw.rectangle([220, 70, target_w-16, 200],
                       fill="#F7F4EF", outline="#E8E2DA", width=1)
        draw.text((236, 84),  "✦ Claude", font=_font_bold(22), fill="#8B5E3C")
        draw.text((236, 114), "以下是整理後的會議重點：",  font=f_md, fill="#3D3D3D")
        draw.text((236, 148), "• 決議事項  • 待辦清單  • 負責人", font=f_sm, fill="#7A6A58")
        draw.rectangle([210, target_h-72, target_w-16, target_h-12],
                       fill="#F7F4EF", outline="#D4B896", width=2)
        draw.text((226, target_h-54), "貼上你的會議記錄文字…", font=f_md, fill="#BBBBBB")
        draw.ellipse([target_w-54, target_h-64, target_w-18, target_h-20], fill="#8B5E3C")
        draw.text((target_w-46, target_h-54), "↑", font=_font_bold(26), fill="white")
    elif "gamma" in (url or "").lower():
        draw.rectangle([0, 48, target_w, 96], fill="#6C47FF")
        draw.text((20, 60), "⚡ Gamma — AI 簡報", font=_font_bold(28), fill="white")
        w3 = (target_w - 60) // 3
        for i,(t,c) in enumerate([("封面","#EEF2FF"),("說明","#F0FDF4"),("結論","#FFF7ED")]):
            x0 = 20 + i*(w3+10)
            draw.rectangle([x0, 110, x0+w3, 340], fill=c, outline="#CCCCCC", width=1)
            draw.text((x0+16, 130), t, font=f_lg, fill="#333333")
    elif "notion" in (url or "").lower():
        draw.text((24, 68), "Notion", font=_font_bold(30), fill="#191919")
        draw.rectangle([20, 110, target_w-20, 150], fill="#F1F1EF", outline="#E3E2E0", width=1)
        draw.text((36, 120), "搜尋或輸入指令…", font=f_md, fill="#AAAAAA")
    else:
        host = (url or "").split("//")[-1].split("/")[0] or "網站"
        draw.text((24, 64), host, font=f_lg, fill="#333333")
        draw.rectangle([20, 100, target_w-20, 340], fill="#FAFAFA", outline="#E5E5E5", width=1)
        wlines = textwrap.wrap(action_label or text or "操作說明", width=28)
        ty = 120
        for wl in wlines[:6]:
            draw.text((36, ty), wl, font=f_md, fill="#444444")
            ty += 40
    # ── 底部提示 ──
    draw.rectangle([0, target_h-40, target_w, target_h], fill="#8B5E3C")
    hint = textwrap.shorten(action_label or text, width=50, placeholder="…")
    draw.text((12, target_h-30), f"▶  {hint}", font=f_sm, fill="#FFE4C4")
    return img

# ── 通用畫面元素 ──────────────────────────────────────────────────────────

def _draw_top_bar(draw: ImageDraw.Draw, title: str = ""):
    draw.rectangle([(0, 0), (W, TOP_BAR)], fill=BRAND_BG)
    fb = _font_bold(36)
    fn = _font(30)
    bw = draw.textlength(BRAND_NAME, font=fb)
    draw.text((40, (TOP_BAR - 36) // 2), BRAND_NAME, font=fb, fill=BRAND_TEXT)
    if title:
        tw = draw.textlength(title, font=fn)
        draw.text(((W - tw) // 2, (TOP_BAR - 30) // 2), title,
                  font=fn, fill=(180, 165, 140))


def _draw_bottom_bar(draw: ImageDraw.Draw, action_label: str = "",
                     step_num: int = 0, total_steps: int = 0):
    draw.rectangle([(0, H - BOT_BAR), (W, H)], fill=ACTION_BG)
    if action_label:
        f = _font(32)
        aw = draw.textlength(action_label, font=f)
        draw.text(((W - aw) // 2, H - BOT_BAR + (BOT_BAR - 32) // 2),
                  action_label, font=f, fill=ACTION_TEXT)
    # 步驟進度圓點
    if total_steps > 0:
        dot_r, gap = 8, 24
        total_w = total_steps * (dot_r * 2) + (total_steps - 1) * gap
        sx = W - total_w - 40
        sy = H - 20
        for i in range(1, total_steps + 1):
            color = BRAND_TEXT if i == step_num else (100, 90, 75)
            draw.ellipse([(sx, sy - dot_r), (sx + dot_r*2, sy + dot_r)], fill=color)
            sx += dot_r * 2 + gap


# ── 卡片：Hook / CTA（全寬置中） ──────────────────────────────────────────

def _make_full_card(text: str, subtitle: str = "", video_title: str = "") -> np.ndarray:
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    _draw_top_bar(draw, video_title)
    _draw_bottom_bar(draw)

    # 裝飾橫線
    draw.rectangle([(100, H//2 - 4), (W - 100, H//2)], fill=DIVIDER_COL)

    fb = _font_bold(80)
    fn = _font(48)

    lines = textwrap.wrap(text, width=22)
    total_h = len(lines) * 96 + (20 if subtitle else 0) + (50 if subtitle else 0)
    y = (H - total_h) // 2 - 30
    for line in lines:
        lw = draw.textlength(line, font=fb)
        draw.text(((W - lw) // 2, y), line, font=fb, fill=HEADING_COL)
        y += 96
    if subtitle:
        y += 20
        sw = draw.textlength(subtitle, font=fn)
        draw.text(((W - sw) // 2, y), subtitle, font=fn, fill=BODY_COL)

    return np.array(img)


# ── 卡片：步驟（左文字 + 右截圖）────────────────────────────────────────

def _make_step_card(step: dict, screenshot_img: Image.Image | None,
                    video_title: str, total_steps: int) -> np.ndarray:
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # 左側背景
    draw.rectangle([(0, TOP_BAR), (LEFT_W + 20, H - BOT_BAR)], fill=STEP_BG)
    # 分隔線
    draw.rectangle([(DIVIDER_X - 2, TOP_BAR), (DIVIDER_X + 2, H - BOT_BAR)], fill=DIVIDER_COL)

    _draw_top_bar(draw, video_title)

    num     = step.get("num", 1)
    heading = step.get("heading", "")
    narr    = step.get("narration", "")
    action  = step.get("action_label", "")

    # ── 步驟編號圓形 ──
    cx, cy, r = 90, TOP_BAR + 80, 48
    draw.ellipse([(cx-r, cy-r), (cx+r, cy+r)], fill=NUM_BG)
    fn_num = _font_bold(52)
    nw = draw.textlength(str(num), font=fn_num)
    draw.text((cx - nw//2, cy - 30), str(num), font=fn_num, fill=NUM_TEXT)

    # ── 步驟標題 ──
    fh = _font_bold(60)
    hw = draw.textlength(heading, font=fh)
    # 超長則縮小
    if hw > LEFT_W - 40:
        fh = _font_bold(46)
    draw.text((40, TOP_BAR + 155), heading, font=fh, fill=HEADING_COL)

    # 橫線
    draw.rectangle([(40, TOP_BAR + 230), (LEFT_W - 20, TOP_BAR + 234)], fill=DIVIDER_COL)

    # ── 旁白文字（自動換行，限制在左欄內不切字）──
    fb     = _font(36)
    max_px = LEFT_W - 80
    tmp_d  = ImageDraw.Draw(Image.new("RGB",(1,1)))
    for cw in range(15, 7, -1):
        test_lines = textwrap.fill(narr, width=cw).split("\n")
        if all(tmp_d.textlength(l, font=fb) <= max_px for l in test_lines):
            break
    y = TOP_BAR + 265
    for line in test_lines[:9]:
        draw.text((40, y), line, font=fb, fill=BODY_COL)
        y += 50

    # ── 右側截圖 ──
    shot = screenshot_img or _placeholder(
        RIGHT_W, CONTENT_H,
        text=heading, url=step.get("url",""), action_label=action,
    )
    img.paste(shot, (RIGHT_X, CONTENT_TOP))

    # 截圖外框
    draw.rectangle(
        [(RIGHT_X - 2, CONTENT_TOP - 2), (RIGHT_X + RIGHT_W + 2, CONTENT_TOP + CONTENT_H + 2)],
        outline=DIVIDER_COL, width=3)

    _draw_bottom_bar(draw, action, num, total_steps)

    return np.array(img)


# ── 淡入淡出 ─────────────────────────────────────────────────────────────

def _fade_clip(base_arr: np.ndarray, duration: float) -> VideoClip:
    def make_frame(t: float) -> np.ndarray:
        if t < FADE_DUR:
            alpha = t / FADE_DUR
        elif t > duration - FADE_DUR:
            alpha = (duration - t) / FADE_DUR
        else:
            alpha = 1.0
        alpha = float(np.clip(alpha, 0.0, 1.0))
        bg    = np.full_like(base_arr, FADE_BG, dtype=np.float32)
        return (alpha * base_arr.astype(np.float32) + (1 - alpha) * bg).astype(np.uint8)
    return VideoClip(make_frame, duration=duration)


# ── 主渲染函式 ───────────────────────────────────────────────────────────

def render_tutorial_video(
    audio_path: str,
    steps: list,
    screenshots: dict,
    title: str = "",
    output: str = "video_final.mp4",
) -> str:
    """
    渲染 16:9 教學影片。

    Args:
        audio_path:  Google TTS 產生的 .mp3
        steps:       [{"num":1,"heading":"...","narration":"...","url":"...","action_label":"..."}]
        screenshots: {step_num: "screenshot_stepN.png"}
        title:       影片標題（顯示在頂部）
        output:      輸出路徑
    """
    print(f"  載入音頻：{audio_path}")
    audio      = AudioFileClip(audio_path)
    total_dur  = audio.duration
    print(f"  音頻時長：{total_dur:.1f} 秒")

    # 時間分配
    n_steps     = len(steps) if steps else 3
    hook_dur    = min(8.0,  total_dur * 0.12)
    cta_dur     = min(10.0, total_dur * 0.15)
    step_total  = total_dur - hook_dur - cta_dur
    step_dur    = step_total / n_steps if n_steps else step_total

    clips = []

    # ── Hook 卡 ──
    hook_text = steps[0].get("narration", title)[:40] if steps else title
    hook_arr  = _make_full_card(title, hook_text, title)
    clips.append(_fade_clip(hook_arr, hook_dur))
    print(f"  Hook 卡：{hook_dur:.1f}秒")

    # ── 步驟卡 ──
    for step in steps:
        num      = step.get("num", 1)
        shot_path = screenshots.get(num)
        shot_img  = None
        if shot_path:
            shot_img = _load_screenshot(shot_path, RIGHT_W, CONTENT_H)
        arr = _make_step_card(step, shot_img, title, n_steps)
        clips.append(_fade_clip(arr, step_dur))
        print(f"  Step {num} 卡：{step_dur:.1f}秒 / 截圖：{'✅' if shot_img else '📋placeholder'}")

    # ── CTA 卡 ──
    cta_arr = _make_full_card("記得訂閱 Vivi AI研習社！", "留言分享你的結果 👇", title)
    clips.append(_fade_clip(cta_arr, cta_dur))
    print(f"  CTA 卡：{cta_dur:.1f}秒")

    # ── 合成 ──
    video = concatenate_videoclips(clips, method="compose")
    video = video.set_audio(audio)

    print(f"  輸出：{output}")
    video.write_videofile(
        output, fps=30, codec="libx264", audio_codec="aac",
        preset="fast", logger=None,
    )

    size_mb = Path(output).stat().st_size // (1024 * 1024)
    print(f"  ✅ 影片完成：{output} ({size_mb} MB)")
    return output
