"""
video_renderer.py — Vivi AI研習社 16:9 教學影片渲染器
風格：AI 教學頻道 — 左側步驟重點，右側「實際 Prompt → AI 輸出」範例卡
目標受眾：台灣上班族（非技術背景）
"""
from __future__ import annotations
import textwrap, numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import AudioFileClip, VideoClip, concatenate_videoclips

# ── 尺寸 ─────────────────────────────────────────────────────────────
W, H        = 1920, 1080
TOP_BAR     = 70
BOT_BAR     = 68
LEFT_W      = 700
DIVIDER_X   = 722
RIGHT_X     = 740
RIGHT_W     = W - RIGHT_X - 18
CONTENT_TOP = TOP_BAR + 6
CONTENT_BOT = H - BOT_BAR - 6
CONTENT_H   = CONTENT_BOT - CONTENT_TOP
FADE_DUR    = 0.15

# ── 配色 ─────────────────────────────────────────────────────────────
BG          = (244, 241, 236)
BRAND_BG    = (38, 28, 18)
BRAND_GOLD  = (210, 165, 80)
LEFT_BG     = (232, 225, 212)
ACCENT      = (172, 92, 48)
ACCENT_DK   = (120, 58, 24)
HEAD_COL    = (28, 20, 12)
BODY_COL    = (72, 54, 36)
BULLET_BG   = ACCENT
BULLET_FG   = (255, 255, 255)
BOT_BG      = (38, 28, 18)
BOT_FG      = (195, 168, 118)
DIV_COL     = ACCENT
FADE_BG     = BG

# 右側 chat 配色
CHAT_BG     = (250, 248, 244)
TOOL_BAR    = (45, 38, 28)
PROMPT_BG   = (232, 245, 232)   # 淺綠 = 使用者輸入
PROMPT_FG   = (20, 80, 20)
OUTPUT_BG   = (245, 240, 232)   # 米白 = AI 輸出
OUTPUT_FG   = (40, 28, 12)
LABEL_BG    = (172, 92, 48)
LABEL_FG    = (255, 255, 255)
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

# ── 上下 Bar ─────────────────────────────────────────────────────────
def _top_bar(draw: ImageDraw.Draw, title: str = ""):
    draw.rectangle([(0, 0), (W, TOP_BAR)], fill=BRAND_BG)
    fb = _font_bold(32); fn = _font(26)
    draw.text((34, (TOP_BAR - 32) // 2), BRAND_NAME, font=fb, fill=BRAND_GOLD)
    if title:
        tw = draw.textlength(title[:48], font=fn)
        draw.text(((W - tw) // 2, (TOP_BAR - 26) // 2),
                  title[:48], font=fn, fill=(168, 148, 108))

def _bot_bar(draw: ImageDraw.Draw, action: str = "", num: int = 0, total: int = 0):
    draw.rectangle([(0, H - BOT_BAR), (W, H)], fill=BOT_BG)
    if action:
        fa = _font(28)
        aw = draw.textlength(action[:70], font=fa)
        draw.text(((W - aw) // 2, H - BOT_BAR + (BOT_BAR - 28) // 2),
                  action[:70], font=fa, fill=BOT_FG)
    if total > 0:
        r, gap = 7, 20
        sx = W - (total * (r * 2 + gap)) - 30
        sy = H - 16
        for i in range(1, total + 1):
            draw.ellipse([(sx, sy - r), (sx + r * 2, sy + r)],
                         fill=BRAND_GOLD if i == num else (75, 60, 40))
            sx += r * 2 + gap

# ── 右側核心：Prompt → AI Output 範例卡 ─────────────────────────────
def _chat_card(tool_name: str, prompt: str, output_lines: list[str],
               tw: int, th: int) -> Image.Image:
    """
    渲染一張仿 AI 工具介面的對話卡：
    ┌─────────────────────┐
    │  🔧 ChatGPT          │  ← 深色 tool bar
    ├─────────────────────┤
    │  你輸入：            │
    │  [prompt 框]        │  ← 淺綠背景
    ├─────────────────────┤
    │  AI 輸出：           │
    │  [output 框]        │  ← 米白背景（多行）
    └─────────────────────┘
    """
    img  = Image.new("RGB", (tw, th), CHAT_BG)
    draw = ImageDraw.Draw(img)

    fsm   = _font(20); fmd = _font(26); flg = _font_bold(28)
    fcode = _font(23)   # 模擬等寬感

    PAD = 22

    # ── Tool bar ──
    bar_h = 52
    draw.rectangle([(0, 0), (tw, bar_h)], fill=TOOL_BAR)
    # 三點
    for cx, col in [(18, "#FF5F57"), (38, "#FEBC2E"), (58, "#28C840")]:
        draw.ellipse([(cx - 7, 18), (cx + 7, 32)], fill=col)
    draw.text((76, 14), tool_name, font=_font_bold(26), fill=(220, 200, 160))

    y = bar_h + PAD

    # ── 使用者 Prompt 區 ──
    label_h = 32
    draw.rectangle([(PAD, y), (tw - PAD, y + label_h)], fill=LABEL_BG)
    draw.text((PAD + 10, y + 4), "✏️  你輸入的指令", font=fsm, fill=LABEL_FG)
    y += label_h + 6

    # Prompt 框
    prompt_lines = []
    for seg in prompt.split("\n"):
        prompt_lines += textwrap.wrap(seg, width=38) or [""]
    prompt_h = max(len(prompt_lines) * 34 + 20, 70)
    draw.rectangle([(PAD, y), (tw - PAD, y + prompt_h)],
                   fill=PROMPT_BG, outline="#A8D8A8", width=2)
    py = y + 10
    for line in prompt_lines[:5]:
        draw.text((PAD + 12, py), line, font=fcode, fill=PROMPT_FG)
        py += 34
    y += prompt_h + PAD

    # ── AI 輸出區 ──
    draw.rectangle([(PAD, y), (tw - PAD, y + label_h)], fill=LABEL_BG)
    draw.text((PAD + 10, y + 4), "🤖  AI 實際輸出", font=fsm, fill=LABEL_FG)
    y += label_h + 6

    # Output 框
    all_out = []
    for line in output_lines:
        all_out += textwrap.wrap(line, width=36) or [""]
    remaining_h = th - y - PAD - 6
    output_h = max(remaining_h, 80)
    draw.rectangle([(PAD, y), (tw - PAD, y + output_h)],
                   fill=OUTPUT_BG, outline="#D4C8A8", width=2)

    oy = y + 12
    line_h = 32
    max_lines = (output_h - 24) // line_h
    for line in all_out[:max_lines]:
        # 重點字加粗顯示（以「•」或「【」開頭）
        col = ACCENT_DK if line.startswith(("•", "【", "✅", "⚠️", "→")) else OUTPUT_FG
        draw.text((PAD + 12, oy), line, font=fcode, fill=col)
        oy += line_h

    return img

# ── 步驟卡（左重點 + 右 Chat 範例）────────────────────────────────────
def _step_card(step: dict, title: str, total: int) -> np.ndarray:
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # 左側背景
    draw.rectangle([(0, TOP_BAR), (LEFT_W + 22, H - BOT_BAR)], fill=LEFT_BG)
    draw.rectangle([(DIVIDER_X - 2, TOP_BAR), (DIVIDER_X + 2, H - BOT_BAR)],
                   fill=DIV_COL)

    _top_bar(draw, title)

    num     = step.get("num", 1)
    heading = step.get("heading", "")
    bullets = step.get("bullets") or []
    action  = step.get("action_label", "")
    tool    = step.get("tool_name", "AI 工具")
    prompt  = step.get("example_prompt", "")
    output  = step.get("example_output") or []

    # ── 步驟編號圓 ──
    cx, cy, r = 84, TOP_BAR + 72, 44
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=ACCENT)
    fn_num = _font_bold(48)
    nw = draw.textlength(str(num), font=fn_num)
    draw.text((cx - nw // 2, cy - 28), str(num), font=fn_num, fill=(255, 255, 255))

    # ── 大標題 ──
    fh = _font_bold(60)
    hw = draw.textlength(heading, font=fh)
    if hw > LEFT_W - 46:
        fh = _font_bold(48)
    draw.text((38, TOP_BAR + 138), heading, font=fh, fill=HEAD_COL)

    # 橫線
    draw.rectangle([(38, TOP_BAR + 218), (LEFT_W - 12, TOP_BAR + 222)], fill=DIV_COL)

    # ── Bullet 重點（3 條，每條 ≤ 16 字）──
    fb_txt = _font(34)
    y = TOP_BAR + 250
    for i, bullet in enumerate(bullets[:3]):
        # 編號方塊
        tag = f"0{i+1}"
        tw2 = draw.textlength(tag, font=_font_bold(20))
        draw.rectangle([(38, y + 2), (38 + 38, y + 38)], fill=ACCENT)
        draw.text((38 + (38 - tw2) // 2, y + 8), tag,
                  font=_font_bold(20), fill=(255, 255, 255))
        # Bullet 文字（嚴格限制寬度）
        btext = bullet[:18]
        draw.text((86, y + 4), btext, font=fb_txt, fill=BODY_COL)
        y += 68

    # ── 底部補充（若空間夠）──
    if y < H - BOT_BAR - 80:
        tip = step.get("tip", "")
        if tip:
            draw.rectangle([(30, y + 10), (LEFT_W - 10, y + 60)],
                           fill=ACCENT_DK, outline=ACCENT, width=0)
            draw.text((46, y + 18), f"💡 {tip[:28]}", font=_font(28), fill=(255, 220, 160))

    # ── 右側 Chat 範例 ──
    chat_img = _chat_card(tool, prompt, output, RIGHT_W, CONTENT_H)
    img.paste(chat_img, (RIGHT_X, CONTENT_TOP))
    draw.rectangle(
        [(RIGHT_X - 2, CONTENT_TOP - 2),
         (RIGHT_X + RIGHT_W + 2, CONTENT_TOP + CONTENT_H + 2)],
        outline=DIV_COL, width=3)

    _bot_bar(draw, action, num, total)
    return np.array(img)

# ── Hook / CTA 全寬卡 ────────────────────────────────────────────────
def _full_card(text: str, subtitle: str = "", title: str = "") -> np.ndarray:
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    _top_bar(draw, title)
    _bot_bar(draw)
    draw.rectangle([(100, H // 2 - 3), (W - 100, H // 2 + 1)], fill=DIV_COL)
    fb = _font_bold(72); fn = _font(44)
    lines = textwrap.wrap(text, width=22)
    total_h = len(lines) * 88 + (56 if subtitle else 0)
    y = (H - total_h) // 2 - 20
    for line in lines:
        lw = draw.textlength(line, font=fb)
        draw.text(((W - lw) // 2, y), line, font=fb, fill=HEAD_COL)
        y += 88
    if subtitle:
        y += 16
        sw = draw.textlength(subtitle, font=fn)
        draw.text(((W - sw) // 2, y), subtitle, font=fn, fill=BODY_COL)
    return np.array(img)

# ── 淡入淡出 ─────────────────────────────────────────────────────────
def _fade(arr: np.ndarray, dur: float) -> VideoClip:
    def frame(t: float) -> np.ndarray:
        a = float(np.clip(min(t / FADE_DUR, 1.0, (dur - t) / FADE_DUR), 0, 1))
        bg = np.full_like(arr, FADE_BG, dtype=np.float32)
        return (a * arr.astype(np.float32) + (1 - a) * bg).astype(np.uint8)
    return VideoClip(frame, duration=dur)

# ── 主渲染 ────────────────────────────────────────────────────────────
def render_tutorial_video(audio_path: str, steps: list, screenshots: dict,
                          title: str = "", output: str = "video_final.mp4") -> str:
    print(f"  載入音頻：{audio_path}")
    audio     = AudioFileClip(audio_path)
    total_dur = audio.duration
    print(f"  音頻時長：{total_dur:.1f}s")

    n     = len(steps) or 3
    h_dur = min(7.0, total_dur * 0.12)
    c_dur = min(8.0, total_dur * 0.13)
    s_dur = (total_dur - h_dur - c_dur) / n
    clips = []

    # Hook
    hook_sub = steps[0].get("narration", "")[:40] if steps else ""
    clips.append(_fade(_full_card(title, hook_sub, title), h_dur))
    print(f"  Hook: {h_dur:.1f}s")

    # 步驟卡（不需要截圖，直接用 example_prompt/output）
    for step in steps:
        arr = _step_card(step, title, n)
        clips.append(_fade(arr, s_dur))
        print(f"  Step {step.get('num')}: {s_dur:.1f}s")

    # CTA
    clips.append(_fade(
        _full_card("訂閱 Vivi AI研習社！",
                   "每週更新 AI 職場實戰技巧  👇 留言你想學的工具", title),
        c_dur))
    print(f"  CTA: {c_dur:.1f}s")

    video = concatenate_videoclips(clips, method="compose")
    video = video.set_audio(audio)
    video.write_videofile(output, fps=30, codec="libx264",
                          audio_codec="aac", preset="fast", logger=None)
    size = Path(output).stat().st_size // (1024 * 1024)
    print(f"  ✅ 完成：{output} ({size} MB)")
    return output
