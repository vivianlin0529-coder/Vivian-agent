"""
video_renderer.py — Vivi AI研習社 16:9 教學影片渲染器
風格：百萬 YouTuber AI 教學風 — 左側大標 + bullet 重點，右側仿真 UI
格式：1920x1080 (16:9)
"""
from __future__ import annotations
import re, textwrap
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import AudioFileClip, VideoClip, ImageClip, concatenate_videoclips

# ── 尺寸 ────────────────────────────────────────────────────────────
W, H      = 1920, 1080
TOP_BAR   = 72
BOT_BAR   = 72
LEFT_W    = 720          # 左側文字區
DIVIDER_X = 740
RIGHT_X   = 760
RIGHT_W   = W - RIGHT_X - 20
CONTENT_TOP = TOP_BAR + 8
CONTENT_BOT = H - BOT_BAR - 8
CONTENT_H   = CONTENT_BOT - CONTENT_TOP

# ── 配色（暖棕教學風）────────────────────────────────────────────────
BG          = (245, 242, 238)
BRAND_BG    = (42, 32, 22)
BRAND_TEXT  = (215, 170, 90)
LEFT_BG     = (235, 229, 218)
ACCENT      = (178, 98, 56)       # 橙棕
ACCENT_DARK = (130, 65, 30)
NUM_BG      = ACCENT
NUM_FG      = (255, 255, 255)
HEAD_COL    = (32, 24, 16)
BODY_COL    = (68, 52, 38)
BULLET_COL  = (88, 60, 32)
BOT_BG      = (42, 32, 22)
BOT_TEXT    = (200, 175, 130)
DIV_COL     = ACCENT
FADE_BG     = BG
FADE_DUR    = 0.18
BRAND_NAME  = "Vivi AI研習社"

# ── 字體 ─────────────────────────────────────────────────────────────
def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/msjh.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]:
        if Path(p).exists():
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()

def _font_bold(size: int) -> ImageFont.FreeTypeFont:
    for p in [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "C:/Windows/Fonts/msjhbd.ttc",
    ]:
        if Path(p).exists():
            try: return ImageFont.truetype(p, size)
            except: pass
    return _font(size)

# ── 截圖載入 ─────────────────────────────────────────────────────────
def _load_screenshot(path: str | None, tw: int, th: int) -> Image.Image | None:
    if not path or not Path(path).exists():
        return None
    try:
        img = Image.open(path).convert("RGB")
        r   = max(tw / img.width, th / img.height)
        img = img.resize((int(img.width*r), int(img.height*r)), Image.LANCZOS)
        l   = (img.width  - tw) // 2
        t   = (img.height - th) // 2
        return img.crop((l, t, l+tw, t+th))
    except Exception as e:
        print(f"  ⚠️ 截圖載入失敗：{e}")
        return None

# ── 仿真瀏覽器 UI（右側 placeholder）────────────────────────────────
def _mock_ui(tw: int, th: int, url: str = "", heading: str = "",
             action_label: str = "") -> Image.Image:
    img  = Image.new("RGB", (tw, th), "#F0EDE8")
    draw = ImageDraw.Draw(img)
    fsm  = _font(18); fmd = _font(24); flg = _font_bold(30); furl = _font(20)

    # 瀏覽器外框
    draw.rectangle([0,0,tw,th], fill="#E8E4DF")
    # 頂部 tab bar
    draw.rectangle([0,0,tw,44], fill="#CCCCCC")
    for cx,col in [(16,"#FF5F57"),(34,"#FEBC2E"),(52,"#28C840")]:
        draw.ellipse([cx-6,16,cx+6,28], fill=col)
    # 網址列
    draw.rectangle([76,8,tw-12,36], fill="white", outline="#AAAAAA", width=1)
    bar_txt = (url or "claude.ai")[:65]
    draw.text((88,13), bar_txt, font=furl, fill="#444")

    # 主內容
    draw.rectangle([0,44,tw,th], fill="white")

    if "claude" in url.lower():
        # 左側欄
        draw.rectangle([0,44,188,th], fill="#F8F5F0")
        draw.text((12,58),  "✦ Claude",   font=_font_bold(22), fill="#8B5E3C")
        draw.text((12,92),  "+ 新對話",    font=fsm,            fill="#888")
        draw.rectangle([4,120,184,152], fill="#EDE9E2")
        draw.text((14,128), "今天的對話",   font=fsm,            fill="#5C4A32")
        # 對話區
        cx0 = 200
        draw.rectangle([cx0,44,tw,th], fill="white")
        # AI 氣泡
        draw.rectangle([cx0+10,60,tw-12,180],
                       fill="#F7F4EF", outline="#E2DDD6", width=1)
        draw.text((cx0+24,74),  "✦ Claude",           font=_font_bold(20), fill="#8B5E3C")
        draw.text((cx0+24,104), "以下是整理後的重點：", font=fmd,            fill="#333")
        draw.text((cx0+24,138), "• 決議  • 待辦  • 負責人", font=fsm, fill="#666")
        # 輸入框
        draw.rectangle([cx0+10,th-64,tw-12,th-10],
                       fill="#F7F4EF", outline="#D4B896", width=2)
        draw.text((cx0+24,th-48), "貼上文字或輸入指令…", font=fmd, fill="#BBB")
        draw.ellipse([tw-50,th-58,tw-16,th-18], fill=ACCENT)
        draw.text((tw-40,th-46), "↑", font=_font_bold(24), fill="white")

    elif "gamma" in url.lower():
        draw.rectangle([0,44,tw,92], fill="#5B3FD9")
        draw.text((18,56), "⚡ Gamma", font=_font_bold(26), fill="white")
        w3 = (tw-48)//3
        for i,(t,c) in enumerate([("封面","#EEF2FF"),("內容","#F0FDF4"),("結論","#FFF7ED")]):
            x0 = 12+i*(w3+12)
            draw.rectangle([x0,100,x0+w3,320], fill=c, outline="#CCC", width=1)
            draw.text((x0+14,116), t, font=flg, fill="#333")

    elif "notion" in url.lower():
        draw.text((22,62), "📝 Notion", font=_font_bold(28), fill="#191919")
        draw.rectangle([18,108,tw-18,148], fill="#F1F1EF", outline="#E0E0E0", width=1)
        draw.text((34,118), "搜尋頁面…", font=fmd, fill="#AAA")

    elif "chat.openai" in url.lower() or "chatgpt" in url.lower():
        draw.rectangle([0,44,tw,92], fill="#10A37F")
        draw.text((18,56), "ChatGPT", font=_font_bold(26), fill="white")
        draw.rectangle([12,100,tw-12,tw//2], fill="#F7F7F8", outline="#E5E5E5", width=1)
        draw.text((26,116), "以下是為你撰寫的專業 Email：", font=fmd, fill="#333")
        draw.text((26,152), "主旨：關於合作事宜的跟進", font=fsm, fill="#555")
        draw.text((26,178), "內文：感謝您的回覆，針對…", font=fsm, fill="#555")
        draw.rectangle([12,th-64,tw-12,th-10], fill="white", outline="#CCC", width=1)
        draw.text((26,th-48), "輸入訊息…", font=fmd, fill="#AAA")

    else:
        host = url.split("//")[-1].split("/")[0] or "操作介面"
        draw.text((20,60), host, font=flg, fill="#333")
        wlines = textwrap.wrap(action_label or heading, width=30)
        ty = 100
        for wl in wlines[:5]:
            draw.text((20,ty), wl, font=fmd, fill="#444")
            ty += 38

    # 底部提示條
    draw.rectangle([0,th-36,tw,th], fill=ACCENT_DARK)
    hint = textwrap.shorten(action_label or heading, width=55, placeholder="…")
    draw.text((10,th-28), f"▶  {hint}", font=fsm, fill=(255,220,170))

    return img

# ── 通用畫面元素 ─────────────────────────────────────────────────────
def _top_bar(draw, title=""):
    draw.rectangle([(0,0),(W,TOP_BAR)], fill=BRAND_BG)
    fb = _font_bold(34); fn = _font(28)
    draw.text((36, (TOP_BAR-34)//2), BRAND_NAME, font=fb, fill=BRAND_TEXT)
    if title:
        tw = draw.textlength(title, font=fn)
        draw.text(((W-tw)//2, (TOP_BAR-28)//2), title, font=fn, fill=(170,150,110))

def _bot_bar(draw, action="", num=0, total=0):
    draw.rectangle([(0,H-BOT_BAR),(W,H)], fill=BOT_BG)
    if action:
        fa = _font(30)
        aw = draw.textlength(action, font=fa)
        draw.text(((W-aw)//2, H-BOT_BAR+(BOT_BAR-30)//2), action, font=fa, fill=BOT_TEXT)
    if total > 0:
        r, gap = 7, 20
        total_w = total*(r*2) + (total-1)*gap
        sx = W - total_w - 36; sy = H - 18
        for i in range(1, total+1):
            draw.ellipse([(sx,sy-r),(sx+r*2,sy+r)],
                         fill=BRAND_TEXT if i==num else (80,65,45))
            sx += r*2 + gap

# ── Hook / CTA 全寬卡 ───────────────────────────────────────────────
def _full_card(text: str, subtitle: str = "", title: str = "") -> np.ndarray:
    img  = Image.new("RGB", (W,H), BG)
    draw = ImageDraw.Draw(img)
    _top_bar(draw, title)
    _bot_bar(draw)
    # 裝飾線
    draw.rectangle([(120, H//2-3),(W-120, H//2+1)], fill=DIV_COL)
    fb = _font_bold(76); fn = _font(46)
    lines = textwrap.wrap(text, width=20)
    total_h = len(lines)*92 + (60 if subtitle else 0)
    y = (H - total_h)//2 - 20
    for line in lines:
        lw = draw.textlength(line, font=fb)
        draw.text(((W-lw)//2, y), line, font=fb, fill=HEAD_COL)
        y += 92
    if subtitle:
        y += 16
        sw = draw.textlength(subtitle, font=fn)
        draw.text(((W-sw)//2, y), subtitle, font=fn, fill=BODY_COL)
    return np.array(img)

# ── 步驟卡（百萬 YouTuber 風：左大標+bullet，右仿真 UI）────────────
def _step_card(step: dict, shot: Image.Image | None,
               title: str, total: int) -> np.ndarray:
    img  = Image.new("RGB", (W,H), BG)
    draw = ImageDraw.Draw(img)

    # 左側背景
    draw.rectangle([(0,TOP_BAR),(LEFT_W+24,H-BOT_BAR)], fill=LEFT_BG)
    # 分隔線
    draw.rectangle([(DIVIDER_X-2,TOP_BAR),(DIVIDER_X+2,H-BOT_BAR)], fill=DIV_COL)

    _top_bar(draw, title)

    num     = step.get("num", 1)
    heading = step.get("heading", "")
    bullets = step.get("bullets", [])
    action  = step.get("action_label", "")
    url     = step.get("url", "")

    # ── 步驟圓形編號 ──
    cx, cy, r = 86, TOP_BAR+76, 46
    draw.ellipse([(cx-r,cy-r),(cx+r,cy+r)], fill=NUM_BG)
    fn_num = _font_bold(50)
    nw = draw.textlength(str(num), font=fn_num)
    draw.text((cx-nw//2, cy-28), str(num), font=fn_num, fill=NUM_FG)

    # ── 大標題 ──
    fh = _font_bold(64)
    hw = draw.textlength(heading, font=fh)
    if hw > LEFT_W - 50:
        fh = _font_bold(50)
    draw.text((40, TOP_BAR+148), heading, font=fh, fill=HEAD_COL)

    # 橫線
    draw.rectangle([(40,TOP_BAR+228),(LEFT_W-16,TOP_BAR+232)], fill=DIV_COL)

    # ── Bullet 重點（百萬 YouTuber 核心：3 個短句）──
    fb_check = _font_bold(38)
    fb_text  = _font(36)
    ICONS    = ["01", "02", "03"]
    y = TOP_BAR + 262

    if bullets:
        for i, bullet in enumerate(bullets[:3]):
            # 編號小方塊
            icon = ICONS[i]
            iw = draw.textlength(icon, font=_font_bold(22))
            draw.rectangle([(40, y+2),(40+36, y+38)], fill=ACCENT)
            draw.text((40+(36-iw)//2, y+6), icon, font=_font_bold(22), fill="white")
            # 文字（限制寬度，不換行）
            btext = bullet[:20]  # 截斷超長 bullet
            draw.text((86, y+4), btext, font=fb_text, fill=BULLET_COL)
            y += 70
    else:
        # fallback: 顯示 narration 的前三句
        narr = step.get("narration","")
        for sent in (narr.split("。")[:3]):
            sent = sent.strip()
            if not sent: continue
            draw.text((40, y), f"• {sent[:18]}", font=fb_text, fill=BODY_COL)
            y += 60

    # ── 右側：截圖 or 仿真 UI ──
    ui = shot or _mock_ui(RIGHT_W, CONTENT_H, url=url,
                          heading=heading, action_label=action)
    img.paste(ui, (RIGHT_X, CONTENT_TOP))
    # 外框
    draw.rectangle(
        [(RIGHT_X-2,CONTENT_TOP-2),(RIGHT_X+RIGHT_W+2,CONTENT_TOP+CONTENT_H+2)],
        outline=DIV_COL, width=3)

    _bot_bar(draw, action, num, total)
    return np.array(img)

# ── 淡入淡出 ─────────────────────────────────────────────────────────
def _fade(arr: np.ndarray, dur: float) -> VideoClip:
    def frame(t):
        a = min(t/FADE_DUR, 1.0, (dur-t)/FADE_DUR)
        a = float(np.clip(a, 0, 1))
        bg = np.full_like(arr, FADE_BG, dtype=np.float32)
        return (a*arr.astype(np.float32) + (1-a)*bg).astype(np.uint8)
    return VideoClip(frame, duration=dur)

# ── 主渲染 ────────────────────────────────────────────────────────────
def render_tutorial_video(audio_path: str, steps: list, screenshots: dict,
                          title: str = "", output: str = "video_final.mp4") -> str:
    print(f"  載入音頻：{audio_path}")
    audio     = AudioFileClip(audio_path)
    total_dur = audio.duration
    print(f"  音頻時長：{total_dur:.1f}s")

    n      = len(steps) or 3
    h_dur  = min(7.0, total_dur * 0.12)
    c_dur  = min(9.0, total_dur * 0.14)
    s_dur  = (total_dur - h_dur - c_dur) / n
    clips  = []

    # Hook
    hook_text = title
    hook_sub  = steps[0].get("narration","")[:36] if steps else ""
    clips.append(_fade(_full_card(hook_text, hook_sub, title), h_dur))
    print(f"  Hook: {h_dur:.1f}s")

    # 步驟卡
    for step in steps:
        num  = step.get("num", 1)
        path = screenshots.get(num)
        shot = _load_screenshot(path, RIGHT_W, CONTENT_H) if path else None
        arr  = _step_card(step, shot, title, n)
        clips.append(_fade(arr, s_dur))
        src  = "✅截圖" if shot else "🖥️仿真UI"
        print(f"  Step {num}: {s_dur:.1f}s / {src}")

    # CTA
    clips.append(_fade(
        _full_card("訂閱 Vivi AI研習社！", "留言你的問題 👇  每週更新 AI 實用技巧", title),
        c_dur))
    print(f"  CTA: {c_dur:.1f}s")

    video = concatenate_videoclips(clips, method="compose")
    video = video.set_audio(audio)
    video.write_videofile(output, fps=30, codec="libx264",
                          audio_codec="aac", preset="fast", logger=None)

    size = Path(output).stat().st_size // (1024*1024)
    print(f"  ✅ 完成：{output} ({size} MB)")
    return output
