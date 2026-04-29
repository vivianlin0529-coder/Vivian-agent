"""
Vivi AI研習社 — 升級版影片渲染器
支援：圖說拆解卡片、步驟動畫、成果動畫、進度指示器
"""

import re, math
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import VideoClip, AudioFileClip, concatenate_videoclips

# ── 品牌色彩 ──────────────────────────────
BG_MAIN      = (245, 240, 235)   # 米白底
BG_DARK      = (40,  32,  28)    # 深棕（結果卡）
BG_STEP      = (255, 250, 245)   # 步驟卡底色
BRAND        = (180, 100, 60)    # 暖橘棕
BRAND_LIGHT  = (230, 180, 140)   # 淺橘
ACCENT       = (80,  60,  40)    # 主文字深棕
WHITE        = (255, 255, 255)
GREEN        = (72,  199, 142)   # 成果綠
STEP_COLORS  = [(230, 100, 80), (80, 160, 220), (100, 190, 120)]  # 步驟色

W, H = 1080, 1920
FPS  = 24
LINE_CHARS = 13

# ── 字型載入 ──────────────────────────────

def font(size: int):
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/msjhbd.ttc",
        "C:/Windows/Fonts/msjh.ttc",
        "C:/Windows/Fonts/mingliu.ttc",
    ]
    for p in candidates:
        if Path(p).exists():
            try: return ImageFont.truetype(p, size)
            except: continue
    return ImageFont.load_default()

def font_bold(size: int):
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "C:/Windows/Fonts/msjhbd.ttc",
        "C:/Windows/Fonts/msjhbd.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            try: return ImageFont.truetype(p, size)
            except: continue
    return font(size)

# ── 文字換行 ──────────────────────────────

def wrap(text: str, max_chars: int) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        cur += ch
        if ch in "，。！？、：,!?:" or len(cur) >= max_chars:
            lines.append(cur.strip())
            cur = ""
    if cur.strip(): lines.append(cur.strip())
    return [l for l in lines if l]

# ── 畫品牌標題列 ──────────────────────────

def draw_header(draw, bg_dark=False):
    brand_text = "Vivi AI研習社"
    f = font(46)
    color = WHITE if bg_dark else BRAND
    bw = draw.textlength(brand_text, font=f)
    draw.text(((W - bw) / 2, 100), brand_text, font=f, fill=color)
    line_color = BRAND_LIGHT if bg_dark else BRAND
    draw.rectangle([(140, 168), (W-140, 173)], fill=line_color)

# ── 畫進度點 ─────────────────────────────

def draw_progress(draw, current: int, total: int, dark=False):
    dot_r = 10
    spacing = 32
    total_w = total * dot_r * 2 + (total - 1) * (spacing - dot_r * 2)
    start_x = (W - total_w) / 2
    y = H - 110
    for i in range(total):
        cx = int(start_x + i * spacing + dot_r)
        if i == current:
            draw.ellipse([cx-dot_r, y-dot_r, cx+dot_r, y+dot_r], fill=BRAND)
        else:
            c = (100, 80, 60) if dark else (200, 185, 170)
            draw.ellipse([cx-dot_r, y-dot_r, cx+dot_r, y+dot_r], fill=c)

# ══════════════════════════════════════════
# 卡片類型 1：勾子卡（大字 + 漸層底）
# ══════════════════════════════════════════

def make_hook_frame(text: str, t: float, duration: float) -> np.ndarray:
    img = Image.new("RGB", (W, H), BG_MAIN)
    draw = ImageDraw.Draw(img)

    # 裝飾漸層色塊（上）
    for i in range(300):
        alpha = int(80 * (1 - i / 300))
        r, g, b = BRAND
        draw.rectangle([(0, i), (W, i+1)], fill=(r, g, b, alpha))

    draw_header(draw)

    # 文字淡入動畫
    progress = min(1.0, t / (duration * 0.4))
    opacity = int(255 * progress)
    y_offset = int(40 * (1 - progress))

    lines = wrap(text, LINE_CHARS)
    f = font_bold(76)
    fsmall = font(56)
    line_h = 96
    total_h = len(lines) * line_h
    y_start = (H - total_h) / 2 - 40 + y_offset

    for i, line in enumerate(lines):
        f_use = f if len(line) <= 8 else fsmall
        lw = draw.textlength(line, font=f_use)
        x = (W - lw) / 2
        y = y_start + i * line_h
        # 文字陰影
        draw.text((x+3, y+3), line, font=f_use, fill=(180, 120, 60))
        draw.text((x, y), line, font=f_use, fill=ACCENT)

    # 底部裝飾
    draw.rectangle([(140, H-168), (W-140, H-163)], fill=BRAND)

    # 套用透明度（淡入）
    if opacity < 255:
        overlay = Image.new("RGB", (W, H), BG_MAIN)
        img = Image.blend(overlay, img, progress)

    return np.array(img)

# ══════════════════════════════════════════
# 卡片類型 2：步驟卡（圖說拆解）
# ══════════════════════════════════════════

def make_step_frame(step_num: int, title: str, detail: str,
                    t: float, duration: float,
                    total_steps: int = 3) -> np.ndarray:
    img = Image.new("RGB", (W, H), BG_STEP)
    draw = ImageDraw.Draw(img)
    draw_header(draw)

    color = STEP_COLORS[(step_num - 1) % len(STEP_COLORS)]

    # 動畫進度（步驟卡從左側滑入）
    progress = min(1.0, t / (duration * 0.35))
    ease = 1 - (1 - progress) ** 3  # ease-out cubic
    slide_x = int((1 - ease) * -W)

    # ── 步驟數字大徽章 ──
    badge_size = 160
    badge_x = 80 + slide_x
    badge_y = 240
    # 圓形底
    draw.ellipse([badge_x, badge_y,
                  badge_x + badge_size, badge_y + badge_size],
                 fill=color)
    # 數字
    f_num = font_bold(90)
    num_str = str(step_num)
    nw = draw.textlength(num_str, font=f_num)
    draw.text((badge_x + (badge_size - nw) / 2,
               badge_y + 28), num_str, font=f_num, fill=WHITE)

    # ── 步驟標題 ──
    f_title = font_bold(62)
    title_x = badge_x + badge_size + 36
    draw.text((title_x, badge_y + 46),
              title, font=f_title, fill=tuple(color))

    # ── 分隔線 ──
    line_y = badge_y + badge_size + 40
    draw.rectangle([(80 + slide_x, line_y),
                    (W - 80 + slide_x, line_y + 4)], fill=(*color, 180))

    # ── 詳細說明（圖說拆解）──
    detail_lines = wrap(detail, LINE_CHARS + 2)
    f_detail = font(58)
    line_h = 80
    y = line_y + 50

    # 文字逐行淡入（錯開時間）
    for i, line in enumerate(detail_lines):
        line_progress = min(1.0, max(0, (t - duration * 0.25 - i * 0.08) / (duration * 0.2)))
        line_opacity = line_progress
        lw = draw.textlength(line, font=f_detail)
        lx = (W - lw) / 2 + slide_x
        ly = y + i * line_h + int(20 * (1 - line_progress))

        if line_opacity > 0:
            # 行底色高亮（交替）
            if i % 2 == 0:
                pad = 12
                draw.rectangle([lx - pad, ly - 8,
                                 lx + lw + pad, ly + 66],
                                fill=(255, 248, 240))
            # 文字
            alpha_text = tuple([*ACCENT, int(255 * line_opacity)])
            draw.text((lx, ly), line, font=f_detail, fill=ACCENT)

    # ── 箭頭圖示（提示繼續）──
    if t > duration * 0.7:
        arr_y = H - 200
        arr_progress = min(1.0, (t - duration * 0.7) / (duration * 0.2))
        arr_x = W // 2
        size = 24
        draw.polygon([
            (arr_x - size, arr_y),
            (arr_x + size, arr_y),
            (arr_x, arr_y + size * 1.3)
        ], fill=(*color, int(180 * arr_progress)))

    # 進度點
    draw_progress(draw, step_num - 1, total_steps + 2)

    return np.array(img)

# ══════════════════════════════════════════
# 卡片類型 3：成果動畫卡
# ══════════════════════════════════════════

def make_result_frame(result_text: str, stat: str,
                      t: float, duration: float) -> np.ndarray:
    img = Image.new("RGB", (W, H), BG_DARK)
    draw = ImageDraw.Draw(img)
    draw_header(draw, bg_dark=True)

    # 成果動畫進度
    check_progress = min(1.0, t / (duration * 0.5))
    ease = 1 - (1 - check_progress) ** 2

    # ── 大勾勾動畫（縮放進入）──
    check_size = int(200 * ease)
    if check_size > 10:
        cx, cy = W // 2, H // 2 - 120
        draw.ellipse([cx - check_size, cy - check_size,
                      cx + check_size, cy + check_size],
                     fill=GREEN)
        f_check = font_bold(int(180 * ease))
        cw = draw.textlength("✓", font=f_check)
        draw.text((cx - cw // 2, cy - int(110 * ease)),
                  "✓", font=f_check, fill=WHITE)

    # ── 成果數字（彈出）──
    stat_progress = min(1.0, max(0, (t - duration * 0.3) / (duration * 0.25)))
    if stat_progress > 0:
        f_stat = font_bold(int(88 * (0.5 + 0.5 * stat_progress)))
        sw = draw.textlength(stat, font=f_stat)
        sy = H // 2 + 120 + int(30 * (1 - stat_progress))
        draw.text(((W - sw) / 2, sy), stat, font=f_stat, fill=GREEN)

    # ── 說明文字（淡入）──
    text_progress = min(1.0, max(0, (t - duration * 0.5) / (duration * 0.25)))
    if text_progress > 0:
        lines = wrap(result_text, LINE_CHARS + 1)
        f_res = font(58)
        line_h = 76
        total_h = len(lines) * line_h
        y = H // 2 + 260
        for i, line in enumerate(lines):
            lw = draw.textlength(line, font=f_res)
            draw.text(((W - lw) / 2, y + i * line_h),
                      line, font=f_res,
                      fill=(*WHITE, int(220 * text_progress)))

    # ── 裝飾粒子（隨機小點）──
    if check_progress > 0.5:
        rng = np.random.default_rng(int(t * 8))
        for _ in range(int(30 * (check_progress - 0.5) * 2)):
            px = int(rng.uniform(80, W - 80))
            py = int(rng.uniform(200, H - 200))
            pr = int(rng.uniform(3, 8))
            pc = STEP_COLORS[int(rng.uniform(0, 3))]
            draw.ellipse([px-pr, py-pr, px+pr, py+pr], fill=pc)

    draw_progress(draw, -1, 5, dark=True)  # 全亮
    return np.array(img)

# ══════════════════════════════════════════
# 卡片類型 4：CTA 卡（行動呼籲）
# ══════════════════════════════════════════

def make_cta_frame(cta_text: str, t: float, duration: float) -> np.ndarray:
    img = Image.new("RGB", (W, H), BG_MAIN)
    draw = ImageDraw.Draw(img)
    draw_header(draw)

    progress = min(1.0, t / (duration * 0.4))

    # 大心（脈動）
    pulse = 1.0 + 0.08 * math.sin(t * 6)
    heart_size = int(90 * pulse * progress)
    if heart_size > 5:
        hx, hy = W // 2, H // 2 - 180
        f_heart = font_bold(heart_size * 2)
        hw = draw.textlength("❤️", font=f_heart)
        draw.text((hx - hw // 2, hy - heart_size), "❤️", font=f_heart, fill=BRAND)

    # 主文字
    lines = wrap(cta_text, LINE_CHARS)
    f_cta = font_bold(60)
    f_sub = font(52)
    line_h = 80
    y = H // 2 - 60
    for i, line in enumerate(lines):
        lp = min(1.0, max(0, (t - i * 0.1) / (duration * 0.3)))
        if lp > 0:
            f_use = f_cta if i == 0 else f_sub
            lw = draw.textlength(line, font=f_use)
            ly = y + i * line_h + int(20 * (1 - lp))
            draw.text(((W - lw) / 2, ly), line, font=f_use, fill=ACCENT)

    # 訂閱按鈕樣式
    btn_progress = min(1.0, max(0, (t - duration * 0.5) / (duration * 0.2)))
    if btn_progress > 0:
        bx, by = W // 2 - 180, H // 2 + 200
        bw, bh = 360, 90
        # 圓角矩形
        draw.rounded_rectangle([bx, by, bx+bw, by+bh],
                                radius=45, fill=BRAND)
        f_btn = font_bold(48)
        btxt = "訂閱 Vivi AI研習社"
        tw = draw.textlength(btxt, font=f_btn)
        draw.text((bx + (bw - tw) / 2, by + 20), btxt, font=f_btn, fill=WHITE)

    draw.rectangle([(140, H-168), (W-140, H-163)], fill=BRAND)
    return np.array(img)

# ══════════════════════════════════════════
# 腳本解析 → 卡片序列
# ══════════════════════════════════════════

def parse_script_to_cards(script: str) -> list[dict]:
    """將腳本解析成卡片類型序列"""
    segs = [s.strip() for s in re.split(r'\n+', script) if s.strip()]
    cards = []
    step_count = 0

    for seg in segs:
        seg_lower = seg.lower()

        # 判斷步驟卡（含「步」「第」「Step」數字+冒號）
        step_match = re.match(r'^第?([一二三123])[步驟：: ]', seg)
        if step_match or any(k in seg for k in ['步驟', 'Step', '第一', '第二', '第三']):
            step_count += 1
            # 拆出標題和細節
            colon_pos = next((i for i, c in enumerate(seg) if c in '：:'), -1)
            if colon_pos > 0 and colon_pos < 20:
                title = seg[:colon_pos].strip()
                detail = seg[colon_pos+1:].strip()
            else:
                title = f"步驟 {step_count}"
                detail = seg
            cards.append({"type": "step", "step_num": step_count,
                          "title": title, "detail": detail})

        # 判斷成果卡（含「省」「完成」「結果」「做出」「分鐘」）
        elif any(k in seg for k in ['省了', '做出了', '完成了', '結果', '現在每天', '幫我省']):
            # 提取數字統計
            stat_match = re.search(r'(\d+[小時分鐘天週個]+)', seg)
            stat = stat_match.group(1) if stat_match else "省時間"
            cards.append({"type": "result", "text": seg, "stat": f"每天省 {stat}"})

        # 判斷 CTA 卡（含訂閱、留言、關注）
        elif any(k in seg for k in ['訂閱', '留言', '記得', '我是 Vivi', '我是Vivi']):
            cards.append({"type": "cta", "text": seg})

        # 其他當勾子卡
        else:
            cards.append({"type": "hook", "text": seg})

    # 確保至少有一個成果卡
    if not any(c["type"] == "result" for c in cards):
        cards.insert(-1, {"type": "result",
                          "text": "用 AI 工具自動完成重複工作",
                          "stat": "每天省 2 小時"})

    return cards

# ══════════════════════════════════════════
# 主渲染函數
# ══════════════════════════════════════════

def render_animated_video(audio_path: str, script: str,
                          output: str = "video_final.mp4") -> str:
    import sys
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print("[video] rendering animated video...")

    audio = AudioFileClip(audio_path)
    total_dur = audio.duration
    cards = parse_script_to_cards(script)
    total_steps = sum(1 for c in cards if c["type"] == "step")
    n = len(cards)
    per_card = total_dur / n

    print(f"  共 {n} 張卡片：{[c['type'] for c in cards]}")

    clips = []
    for i, card in enumerate(cards):
        dur = per_card
        ctype = card["type"]

        if ctype == "hook":
            text = card["text"]
            make_frame = lambda t, txt=text, d=dur: make_hook_frame(txt, t, d)

        elif ctype == "step":
            sn = card["step_num"]
            title = card["title"]
            detail = card["detail"]
            ts = total_steps
            make_frame = lambda t, s=sn, ti=title, de=detail, d=dur, ts=ts: \
                make_step_frame(s, ti, de, t, d, ts)

        elif ctype == "result":
            text = card["text"]
            stat = card.get("stat", "省時間")
            make_frame = lambda t, txt=text, st=stat, d=dur: \
                make_result_frame(txt, st, t, d)

        elif ctype == "cta":
            text = card["text"]
            make_frame = lambda t, txt=text, d=dur: make_cta_frame(txt, t, d)

        else:
            text = card.get("text", "")
            make_frame = lambda t, txt=text, d=dur: make_hook_frame(txt, t, d)

        clip = VideoClip(make_frame, duration=dur).with_fps(FPS)
        clips.append(clip)

    print("  合併並加入音訊...")
    final = concatenate_videoclips(clips, method="compose").with_audio(audio)
    final.write_videofile(output, fps=FPS, codec="libx264",
                          audio_codec="aac", logger=None)
    audio.close()

    sz = Path(output).stat().st_size
    print(f"  ✅ 完成：{output} ({sz // 1024} KB)")
    return output
