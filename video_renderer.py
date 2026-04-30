"""
video_renderer.py — Vivi AI研習社 動態教學影片渲染器
格式：1920x1080 / 15fps / 約 2-2.5 分鐘
架構：
  [0-28s]  痛點場景 → 成果預覽
  [28s~]   每步驟：標題(3s) → 打字動畫(10s) → AI思考(3s) → 輸出串流(12s)
  [尾]     CTA
聲音同步：旁白按段落分配到各階段，做到畫面說什麼、嘴巴說什麼
"""
from __future__ import annotations
import textwrap, math, numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import AudioFileClip, VideoClip, concatenate_videoclips

# ── 畫面尺寸 ─────────────────────────────────────────────────────────
W, H     = 1920, 1080
FPS      = 15          # 教學影片 15fps 足夠，省渲染時間
TOP_H    = 68
BOT_H    = 64
AREA_TOP = TOP_H + 4
AREA_BOT = H - BOT_H - 4
AREA_H   = AREA_BOT - AREA_TOP
LEFT_W   = 680
SEP_X    = 700
RIGHT_X  = 718
RIGHT_W  = W - RIGHT_X - 16

# ── 配色 ─────────────────────────────────────────────────────────────
C = dict(
    bg        = (243, 240, 235),
    brand_bg  = (36, 26, 14),
    brand_gold= (208, 162, 72),
    left_bg   = (230, 222, 208),
    sep       = (165, 88, 42),
    accent    = (165, 88, 42),
    accent_dk = (110, 54, 18),
    head      = (26, 18, 8),
    body      = (70, 50, 32),
    bot_bg    = (36, 26, 14),
    bot_fg    = (190, 164, 112),
    # chat
    chat_bg   = (252, 250, 246),
    tool_bar  = (42, 34, 22),
    prompt_bg = (228, 245, 224),
    prompt_fg = (18, 72, 18),
    out_bg    = (246, 241, 230),
    out_fg    = (34, 24, 10),
    cursor    = (165, 88, 42),
    thinking  = (120, 100, 70),
    lbl_bg    = (165, 88, 42),
    lbl_fg    = (255, 255, 255),
    # 痛點/成果
    pain_bg   = (255, 248, 245),
    pain_red  = (200, 40, 20),
    win_bg    = (242, 250, 242),
    win_grn   = (20, 140, 40),
)
BRAND = "Vivi AI研習社"

# ── 字體快取 ─────────────────────────────────────────────────────────
_FC: dict = {}
def _f(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key not in _FC:
        paths_b = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                   "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
                   "C:/Windows/Fonts/msjhbd.ttc"]
        paths_r = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                   "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                   "C:/Windows/Fonts/msjh.ttc"]
        for p in (paths_b if bold else paths_r):
            if Path(p).exists():
                try:
                    _FC[key] = ImageFont.truetype(p, size)
                    break
                except: pass
        if key not in _FC:
            _FC[key] = ImageFont.load_default()
    return _FC[key]

# ── 通用 Bar ─────────────────────────────────────────────────────────
def _top(draw, title=""):
    draw.rectangle([(0,0),(W,TOP_H)], fill=C["brand_bg"])
    draw.text((32,(TOP_H-32)//2), BRAND, font=_f(32,True), fill=C["brand_gold"])
    if title:
        t = title[:50]
        tw = draw.textlength(t, font=_f(26))
        draw.text(((W-tw)//2,(TOP_H-26)//2), t, font=_f(26), fill=(164,142,100))

def _bot(draw, hint="", num=0, total=0):
    draw.rectangle([(0,H-BOT_H),(W,H)], fill=C["bot_bg"])
    if hint:
        hw = draw.textlength(hint[:72], font=_f(26))
        draw.text(((W-hw)//2, H-BOT_H+(BOT_H-26)//2), hint[:72], font=_f(26), fill=C["bot_fg"])
    if total:
        r, g = 7, 18
        sx = W - (total*(r*2+g)) - 28; sy = H-14
        for i in range(1, total+1):
            draw.ellipse([(sx,sy-r),(sx+r*2,sy+r)],
                         fill=C["brand_gold"] if i==num else (72,58,36))
            sx += r*2+g

# ══════════════════════════════════════════════════════════════════════
# HOOK：痛點 → 成果（前28秒）
# ══════════════════════════════════════════════════════════════════════
def _hook_clip(pain_lines: list[str], win_lines: list[str],
               title: str, narr_hook: str, total_dur: float) -> VideoClip:
    """
    0%~45%: 痛點畫面（紅X，描述問題）
    45%~55%: 過渡
    55%~100%: 成果畫面（綠勾，展示AI輸出）
    """
    SWITCH = 0.48

    def _base(bg_col):
        img = Image.new("RGB",(W,H), bg_col)
        draw = ImageDraw.Draw(img)
        _top(draw, title)
        _bot(draw)
        return img, draw

    # ── 預先渲染靜態幀（痛點 & 成果）
    def _pain_frame():
        img, draw = _base(C["pain_bg"])
        # 大X
        draw.text((W//2 - 80, AREA_TOP + 30), "✕", font=_f(120,True), fill=C["pain_red"])
        draw.text((W//2 - 400, AREA_TOP + 180), "現在的你：", font=_f(48,True), fill=C["pain_red"])
        y = AREA_TOP + 250
        for line in pain_lines[:5]:
            draw.text((W//2 - 380, y), f"• {line}", font=_f(40), fill=(100,40,20))
            y += 60
        return np.array(img)

    def _win_frame():
        img, draw = _base(C["win_bg"])
        draw.text((W//2 - 80, AREA_TOP + 30), "✓", font=_f(120,True), fill=C["win_grn"])
        draw.text((W//2 - 400, AREA_TOP + 180), "用 AI 之後：", font=_f(48,True), fill=C["win_grn"])
        y = AREA_TOP + 250
        for line in win_lines[:5]:
            draw.text((W//2 - 380, y), f"✅ {line}", font=_f(40), fill=(20,80,20))
            y += 60
        # 大標
        tw_t = draw.textlength(title, font=_f(52,True))
        draw.text(((W-tw_t)//2, AREA_BOT - 100), title, font=_f(52,True), fill=C["accent"])
        return np.array(img)

    pain_arr = _pain_frame()
    win_arr  = _win_frame()
    fade_dur = 0.4

    def frame(t):
        p = t / total_dur
        if p < SWITCH - fade_dur/total_dur:
            return pain_arr
        elif p < SWITCH + fade_dur/total_dur:
            # 漸變
            alpha = (p - (SWITCH - fade_dur/total_dur)) / (2*fade_dur/total_dur)
            alpha = float(np.clip(alpha, 0, 1))
            return (alpha * win_arr.astype(np.float32) +
                    (1-alpha) * pain_arr.astype(np.float32)).astype(np.uint8)
        else:
            return win_arr

    return VideoClip(frame, duration=total_dur)

# ══════════════════════════════════════════════════════════════════════
# STEP：打字 → AI思考 → 輸出串流（口說同步）
# ══════════════════════════════════════════════════════════════════════
def _step_clip(step: dict, title: str, total: int, total_dur: float) -> VideoClip:
    """
    時間段：
      0%~8%   : 步驟標題出現
      8%~52%  : Prompt 打字動畫
      52%~65% : AI 思考中...（轉圈點點）
      65%~100%: AI 輸出串流
    """
    T_TITLE = 0.08
    T_TYPING = 0.52
    T_THINK  = 0.65
    T_OUTPUT = 1.00

    num     = step.get("num", 1)
    heading = step.get("heading", "")
    bullets = step.get("bullets") or []
    action  = step.get("action_label", "")
    tool    = step.get("tool_name", "Claude")
    prompt  = step.get("example_prompt", "").strip()
    output  = step.get("example_output") or []
    tip     = step.get("tip", "")
    output_text = "\n".join(output)

    # ── 預算靜態左側 ──
    def _left(img: Image.Image, draw: ImageDraw.Draw):
        draw.rectangle([(0,TOP_H),(LEFT_W+18,H-BOT_H)], fill=C["left_bg"])
        draw.rectangle([(SEP_X-2,TOP_H),(SEP_X+2,H-BOT_H)], fill=C["sep"])
        # 編號圓
        cx,cy,r = 80,TOP_H+68,42
        draw.ellipse([(cx-r,cy-r),(cx+r,cy+r)], fill=C["accent"])
        nw = draw.textlength(str(num), font=_f(44,True))
        draw.text((cx-nw//2,cy-26), str(num), font=_f(44,True), fill=(255,255,255))
        # 標題
        fh = _f(56,True)
        hw = draw.textlength(heading, font=fh)
        fh = _f(44,True) if hw > LEFT_W-44 else fh
        draw.text((36, TOP_H+126), heading, font=fh, fill=C["head"])
        # 橫線
        draw.rectangle([(36,TOP_H+202),(LEFT_W-10,TOP_H+206)], fill=C["sep"])
        # Bullets
        y = TOP_H+228
        for i, b in enumerate(bullets[:3]):
            iw = draw.textlength(f"0{i+1}", font=_f(18,True))
            draw.rectangle([(36,y+2),(36+36,y+36)], fill=C["accent"])
            draw.text((36+(36-iw)//2, y+8), f"0{i+1}", font=_f(18,True), fill=(255,255,255))
            draw.text((82, y+4), b[:18], font=_f(32), fill=C["body"])
            y += 62
        # Tip
        if tip and y < H-BOT_H-72:
            draw.rectangle([(28,y+12),(LEFT_W-8,y+60)],
                           fill=C["accent_dk"])
            draw.text((44, y+20), f"💡 {tip[:26]}", font=_f(26), fill=(255,220,150))

    # 預渲染左側 base（不含右側動態內容）
    _base_img = Image.new("RGB",(W,H), C["bg"])
    _base_draw = ImageDraw.Draw(_base_img)
    _top(_base_draw, title)
    _bot(_base_draw, action, num, total)
    _left(_base_img, _base_draw)
    _base_arr = np.array(_base_img)

    # ── 右側 Chat 面板（固定部分）──
    CHAT_TOP = AREA_TOP
    CHAT_H   = AREA_H
    CHAT_PAD = 18
    BAR_H    = 48
    LBL_H    = 30

    # Prompt 文字 wrap
    prompt_lines = []
    for seg in prompt.split("\n"):
        prompt_lines += textwrap.wrap(seg, width=36) or [""]
    PROMPT_LINE_H = 32
    PROMPT_BOX_H  = max(len(prompt_lines)*PROMPT_LINE_H + 20, 80)

    # Output 文字 wrap
    out_lines_all = []
    for line in output:
        out_lines_all += textwrap.wrap(line, width=34) or [""]

    OUT_START_Y = (CHAT_TOP + BAR_H + CHAT_PAD + LBL_H + 6 +
                   PROMPT_BOX_H + CHAT_PAD + LBL_H + 6)
    OUT_AVAIL   = H - BOT_H - 6 - OUT_START_Y - CHAT_PAD
    OUT_LINE_H  = 31
    MAX_OUT_LINES = max(1, OUT_AVAIL // OUT_LINE_H)

    def _draw_right(arr: np.ndarray, shown_prompt: str, shown_output: str,
                    thinking_dots: int) -> np.ndarray:
        img  = Image.fromarray(arr.copy())
        draw = ImageDraw.Draw(img)
        rx   = RIGHT_X

        # Chat 背景
        draw.rectangle([(rx, CHAT_TOP),(W-16, H-BOT_H-6)], fill=C["chat_bg"])
        # Tool bar
        draw.rectangle([(rx, CHAT_TOP),(W-16, CHAT_TOP+BAR_H)], fill=C["tool_bar"])
        for cx,col in [(rx+16,"#FF5F57"),(rx+34,"#FEBC2E"),(rx+52,"#28C840")]:
            draw.ellipse([(cx-6,CHAT_TOP+18),(cx+6,CHAT_TOP+28)], fill=col)
        draw.text((rx+70, CHAT_TOP+12), tool, font=_f(26,True), fill=(215,190,140))

        y = CHAT_TOP + BAR_H + CHAT_PAD

        # Prompt label
        draw.rectangle([(rx+CHAT_PAD, y),(W-28, y+LBL_H)], fill=C["lbl_bg"])
        draw.text((rx+CHAT_PAD+8, y+5), "✏️  你輸入的指令", font=_f(18), fill=C["lbl_fg"])
        y += LBL_H + 6

        # Prompt box
        draw.rectangle([(rx+CHAT_PAD, y),(W-28, y+PROMPT_BOX_H)],
                       fill=C["prompt_bg"], outline="#9ED09E", width=2)
        py = y + 10
        for line in shown_prompt.split("\n")[:int((PROMPT_BOX_H-20)/PROMPT_LINE_H)+1]:
            for wl in textwrap.wrap(line, width=36) or [line]:
                draw.text((rx+CHAT_PAD+10, py), wl, font=_f(23), fill=C["prompt_fg"])
                py += PROMPT_LINE_H
        y += PROMPT_BOX_H + CHAT_PAD

        # Output label
        draw.rectangle([(rx+CHAT_PAD, y),(W-28, y+LBL_H)], fill=C["lbl_bg"])
        draw.text((rx+CHAT_PAD+8, y+5), "🤖  AI 輸出結果", font=_f(18), fill=C["lbl_fg"])
        y += LBL_H + 6

        # Output box
        out_box_h = H - BOT_H - 6 - y - CHAT_PAD
        draw.rectangle([(rx+CHAT_PAD, y),(W-28, y+out_box_h)],
                       fill=C["out_bg"], outline="#C8B878", width=2)

        if thinking_dots >= 0:
            dots = "●" * thinking_dots + "○" * (3 - thinking_dots)
            draw.text((rx+CHAT_PAD+12, y+12),
                      f"AI 思考中  {dots}", font=_f(28), fill=C["thinking"])
        else:
            oy = y + 10
            for line in shown_output.split("\n"):
                if oy + OUT_LINE_H > y + out_box_h - 8: break
                col = C["accent_dk"] if line.startswith(("•","【","✅","⚠️","→","—")) else C["out_fg"]
                draw.text((rx+CHAT_PAD+12, oy), line[:38], font=_f(23), fill=col)
                oy += OUT_LINE_H

        # 外框
        draw.rectangle(
            [(rx-2, CHAT_TOP-2),(W-14, H-BOT_H-4)],
            outline=C["sep"], width=3)

        return np.array(img)

    def frame(t: float) -> np.ndarray:
        p = t / total_dur

        if p < T_TITLE:
            # 步驟標題進場（只有左側，右側空白）
            img  = Image.fromarray(_base_arr.copy())
            draw = ImageDraw.Draw(img)
            draw.rectangle([(RIGHT_X, CHAT_TOP),(W-16, H-BOT_H-6)], fill=C["chat_bg"])
            draw.rectangle([(RIGHT_X-2,CHAT_TOP-2),(W-14,H-BOT_H-4)], outline=C["sep"], width=3)
            draw.text((RIGHT_X+60, AREA_TOP+60), f"Step {num}：{heading}",
                      font=_f(48,True), fill=C["accent"])
            draw.text((RIGHT_X+60, AREA_TOP+130), "準備開始…",
                      font=_f(36), fill=C["thinking"])
            return np.array(img)

        elif p < T_TYPING:
            # 打字動畫
            typing_p = (p - T_TITLE) / (T_TYPING - T_TITLE)
            n = int(typing_p * len(prompt))
            shown = prompt[:n]
            # 閃爍游標（每0.6秒閃一次）
            if int(t / 0.6) % 2 == 0:
                shown += "▋"
            return _draw_right(_base_arr, shown, "", -2)

        elif p < T_THINK:
            # 完整 prompt，AI思考動畫
            dots = int(((p - T_TYPING) / (T_THINK - T_TYPING)) * 4) % 4
            return _draw_right(_base_arr, prompt, "", dots)

        else:
            # 輸出串流
            out_p = (p - T_THINK) / (T_OUTPUT - T_THINK)
            n = int(out_p * len(output_text))
            shown_out = output_text[:n]
            return _draw_right(_base_arr, prompt, shown_out, -1)

    return VideoClip(frame, duration=total_dur)

# ══════════════════════════════════════════════════════════════════════
# CTA
# ══════════════════════════════════════════════════════════════════════
def _cta_clip(title: str, dur: float) -> VideoClip:
    img  = Image.new("RGB",(W,H), C["bg"])
    draw = ImageDraw.Draw(img)
    _top(draw, title)
    _bot(draw)
    draw.rectangle([(120, H//2-3),(W-120,H//2+1)], fill=C["sep"])
    lines = ["🔔 訂閱 Vivi AI研習社", "每週更新 AI 職場實戰技巧"]
    y = H//2 - 90
    for i,l in enumerate(lines):
        lw = draw.textlength(l, font=_f(60 if i==0 else 44, i==0))
        draw.text(((W-lw)//2, y), l, font=_f(60 if i==0 else 44, i==0),
                  fill=C["head"] if i==0 else C["body"])
        y += 90
    y += 20
    sub = "👇 留言你的問題，我都會回覆"
    sw = draw.textlength(sub, font=_f(38))
    draw.text(((W-sw)//2, y), sub, font=_f(38), fill=C["accent"])
    arr = np.array(img)
    return VideoClip(lambda t: arr, duration=dur)

# ══════════════════════════════════════════════════════════════════════
# 主渲染入口
# ══════════════════════════════════════════════════════════════════════
def render_tutorial_video(audio_path: str, steps: list, screenshots: dict,
                          title: str = "", output: str = "video_final.mp4") -> str:
    print(f"  音頻：{audio_path}")
    audio     = AudioFileClip(audio_path)
    total_dur = audio.duration
    print(f"  時長：{total_dur:.1f}s  步驟：{len(steps)}")

    n      = len(steps) or 3
    hook_d = min(28.0, total_dur * 0.20)
    cta_d  = min(12.0, total_dur * 0.10)
    step_d = (total_dur - hook_d - cta_d) / n
    clips  = []

    # ── Hook ──
    pain_lines = steps[0].get("pain_points") or []
    win_lines  = steps[0].get("win_points")  or []
    if not pain_lines:
        pain_lines = ["花了30分鐘寫 Email，對方一句話否定",
                      "會議記錄整理2小時，重點還是漏掉",
                      "不知道怎麼下指令，AI 的輸出很雞肋"]
    if not win_lines:
        win_lines  = ["30秒內產出專業 Email 草稿",
                      "會議記錄自動整理成重點＋待辦",
                      "學會 Prompt 技巧，AI 輸出精準有用"]
    clips.append(_hook_clip(pain_lines, win_lines, title,
                            steps[0].get("narration",""), hook_d))
    print(f"  Hook: {hook_d:.1f}s")

    # ── Steps ──
    for step in steps:
        clips.append(_step_clip(step, title, n, step_d))
        print(f"  Step {step.get('num')}: {step_d:.1f}s  "
              f"prompt={len(step.get('example_prompt',''))}chars  "
              f"output={len(step.get('example_output',[]))}lines")

    # ── CTA ──
    clips.append(_cta_clip(title, cta_d))
    print(f"  CTA: {cta_d:.1f}s")

    video = concatenate_videoclips(clips, method="compose")
    video = video.set_audio(audio)
    video.write_videofile(output, fps=FPS, codec="libx264",
                          audio_codec="aac", preset="fast", logger=None)
    size = Path(output).stat().st_size // (1024*1024)
    print(f"  ✅ 完成：{output} ({size} MB)")
    return output
