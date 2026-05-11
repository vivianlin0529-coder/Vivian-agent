"""
video_renderer.py — Vivi AI研習社
- 封面：Unsplash 真實高質照片（辦公室/電腦/Email 情境）
- Step 1/2：打字動畫 + AI 輸出串流
- Step 3（簡報類）：渲染真實 Gamma 風格簡報預覽圖
- 口說/畫面嚴格同步
- 總長 ≤ 60 秒
"""
from __future__ import annotations
import textwrap, requests, io, numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
try:
    from moviepy.editor import AudioFileClip, VideoClip, concatenate_videoclips
except ImportError:
    from moviepy import AudioFileClip, VideoClip, concatenate_videoclips

W, H   = 1920, 1080
FPS    = 15
TOP_H  = 64; BOT_H = 60
AY = TOP_H + 4; AB = H - BOT_H - 4; AH = AB - AY
LW = 680; RX = 726; RW = W - RX - 14
BRAND = "Vivi AI研習社"

C = dict(
    bg=(242,239,234), brand_bg=(34,24,12), gold=(206,158,68),
    sep=(160,84,38),  accent=(160,84,38),  acdk=(108,50,14),
    hd=(24,16,6),     bd=(68,48,28),       lbg=(228,220,206),
    bot_bg=(34,24,12),bot_fg=(188,160,108),
    cbg=(252,250,246),tbar=(40,30,18),
    pbg=(226,244,222),pfg=(16,70,16),
    obg=(246,240,228),ofg=(32,22,8),
    lbl=(160,84,38),  lblf=(255,255,255),
    think=(118,96,64),acdk2=(108,50,14),
    pain_r=(195,35,18),pain_txt=(88,28,12),
    win_g=(18,132,38), win_txt=(12,64,18),
)

_FC: dict = {}
def _f(sz, bold=False):
    k = (sz, bold)
    if k not in _FC:
        pb = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
              "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"]
        pr = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"]
        for p in (pb if bold else pr):
            if Path(p).exists():
                try: _FC[k] = ImageFont.truetype(p, sz); break
                except: pass
        if k not in _FC: _FC[k] = ImageFont.load_default()
    return _FC[k]


def _safe_text(draw, xy, text, font, fill, max_width=None):
    """繪製文字，自動截斷確保不超出 max_width"""
    if not text:
        return
    if max_width is None:
        draw.text(xy, text, font=font, fill=fill)
        return
    # 逐字截斷直到寬度 ≤ max_width
    while len(text) > 0:
        w = draw.textlength(text, font=font)
        if w <= max_width:
            break
        text = text[:-1]
    if text:
        draw.text(xy, text, font=font, fill=fill)

def _safe_wrap(draw, x, y, text, font, fill, max_width, line_height, max_lines=99):
    """自動換行繪製，確保每行不超出 max_width"""
    import textwrap as _tw
    if not text:
        return y
    # 先算出合適的 char width（粗估）
    avg_char_w = draw.textlength("測", font=font)
    chars_per_line = max(1, int(max_width / avg_char_w))
    lines = []
    for seg in text.split("\n"):
        wrapped = _tw.wrap(seg, width=chars_per_line) if seg else [""]
        lines.extend(wrapped)
    drawn = 0
    for line in lines:
        if drawn >= max_lines:
            break
        # 再次確保單行不超出
        while line and draw.textlength(line, font=font) > max_width:
            line = line[:-1]
        if line:
            draw.text((x, y), line, font=font, fill=fill)
            y += line_height
            drawn += 1
    return y


def _top(draw, title=""):
    draw.rectangle([(0,0),(W,TOP_H)], fill=C["brand_bg"])
    draw.text((30,(TOP_H-30)//2), BRAND, font=_f(30,True), fill=C["gold"])
    if title:
        tw = draw.textlength(title[:50], font=_f(24))
        draw.text(((W-tw)//2,(TOP_H-24)//2), title[:50], font=_f(24), fill=(155,133,92))

def _bot(draw, hint="", num=0, total=0):
    draw.rectangle([(0,H-BOT_H),(W,H)], fill=C["bot_bg"])
    if hint:
        # 自動縮短至單行不超出畫面
        h_text = hint
        while h_text and draw.textlength(h_text, font=_f(23)) > W - 80:
            h_text = h_text[:-1]
        hw = draw.textlength(h_text, font=_f(23))
        draw.text(((W-hw)//2, H-BOT_H+(BOT_H-23)//2), h_text, font=_f(23), fill=C["bot_fg"])
    if total:
        r, g = 6, 16; sx = W-(total*(r*2+g))-22; sy = H-12
        for i in range(1, total+1):
            draw.ellipse([(sx,sy-r),(sx+r*2,sy+r)],
                         fill=C["gold"] if i==num else (66,52,30))
            sx += r*2+g

def _audio_dur(path):
    try: return AudioFileClip(path).duration
    except: return 7.0

# ══════════════════════════════════════════════════════
# Unsplash 真實照片下載
# ══════════════════════════════════════════════════════

# ── Pexels 辦公室情境照片庫（直連，均為真實辦公室/職場場景）─────────
PEXELS_PAIN = [
    # ── 痛點情境圖庫（辦公室壓力/加班/焦慮）
    "https://images.pexels.com/photos/5699678/pexels-photo-5699678.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/4101143/pexels-photo-4101143.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3760810/pexels-photo-3760810.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/7688336/pexels-photo-7688336.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3799832/pexels-photo-3799832.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/4491461/pexels-photo-4491461.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/1496193/pexels-photo-1496193.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3184418/pexels-photo-3184418.jpeg?auto=compress&cs=tinysrgb&w=1920",
]
PEXELS_WIN = [
    # ── 成功/效率/成果圖庫
    "https://images.pexels.com/photos/3184291/pexels-photo-3184291.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3182812/pexels-photo-3182812.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/5255215/pexels-photo-5255215.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3184360/pexels-photo-3184360.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3184465/pexels-photo-3184465.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/1181354/pexels-photo-1181354.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3184433/pexels-photo-3184433.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/7688160/pexels-photo-7688160.jpeg?auto=compress&cs=tinysrgb&w=1920",
]

# ── Hook 主題設定（6種輪替，每篇視覺完全不同）──
HOOK_THEMES = [
    # 主題 0：紅色警示 — 標準版（原版改良）
    dict(
        pain_bg=(255, 240, 238), pain_left=(255, 225, 220),
        pain_accent=(195, 35, 18), pain_txt=(88, 28, 12),
        pain_label="⚠  工作中的你", pain_bullet="✗",
        pain_overlay=(130, 15, 5), pain_overlay_alpha=70,
        win_bg=(240, 252, 244), win_left=(220, 248, 226),
        win_accent=(18, 132, 38), win_txt=(12, 64, 18),
        win_label="✓  用 AI 之後", win_bullet="✓",
        win_overlay=(8, 60, 18), win_overlay_alpha=55,
        win_badge="AI 幫你 30 秒搞定",
    ),
    # 主題 1：深藍商務 — 數字衝擊
    dict(
        pain_bg=(235, 240, 252), pain_left=(215, 228, 250),
        pain_accent=(30, 60, 180), pain_txt=(20, 40, 120),
        pain_label="📊  你每天浪費的時間",  pain_bullet="▶",
        pain_overlay=(10, 30, 100), pain_overlay_alpha=75,
        win_bg=(235, 250, 255), win_left=(210, 242, 255),
        win_accent=(0, 120, 200), win_txt=(0, 70, 140),
        win_label="🚀  AI 接手後", win_bullet="▶",
        win_overlay=(0, 60, 120), win_overlay_alpha=60,
        win_badge="效率提升 10x",
    ),
    # 主題 2：橘色緊迫 — 截止日期感
    dict(
        pain_bg=(255, 245, 235), pain_left=(255, 230, 210),
        pain_accent=(200, 80, 0), pain_txt=(120, 50, 0),
        pain_label="🔥  Deadline 壓力",  pain_bullet="！",
        pain_overlay=(140, 50, 0), pain_overlay_alpha=65,
        win_bg=(255, 252, 235), win_left=(255, 248, 210),
        win_accent=(180, 130, 0), win_txt=(100, 75, 0),
        win_label="⚡  AI 加速完成", win_bullet="★",
        win_overlay=(110, 80, 0), win_overlay_alpha=55,
        win_badge="準時交件 不再趕",
    ),
    # 主題 3：暗紫科技感 — 現代感
    dict(
        pain_bg=(245, 238, 255), pain_left=(232, 218, 255),
        pain_accent=(120, 30, 190), pain_txt=(70, 15, 120),
        pain_label="😩  你卡關的地方", pain_bullet="▸",
        pain_overlay=(80, 10, 140), pain_overlay_alpha=70,
        win_bg=(238, 245, 255), win_left=(218, 232, 255),
        win_accent=(30, 90, 200), win_txt=(15, 55, 130),
        win_label="✨  AI 一鍵解決", win_bullet="◆",
        win_overlay=(10, 50, 150), win_overlay_alpha=60,
        win_badge="從此不再卡關",
    ),
    # 主題 4：黑金質感 — 高端職場
    dict(
        pain_bg=(245, 242, 235), pain_left=(230, 224, 208),
        pain_accent=(120, 85, 20), pain_txt=(70, 50, 10),
        pain_label="📌  職場痛點", pain_bullet="•",
        pain_overlay=(60, 40, 5), pain_overlay_alpha=80,
        win_bg=(245, 248, 240), win_left=(228, 238, 218),
        win_accent=(50, 120, 30), win_txt=(25, 70, 15),
        win_label="💼  AI 職場升級", win_bullet="◉",
        win_overlay=(20, 70, 10), win_overlay_alpha=65,
        win_badge="職場競爭力 UP",
    ),
    # 主題 5：青藍清新 — 輕鬆效率
    dict(
        pain_bg=(235, 250, 255), pain_left=(210, 240, 255),
        pain_accent=(0, 140, 180), pain_txt=(0, 80, 110),
        pain_label="😓  每天都在重複",  pain_bullet="→",
        pain_overlay=(0, 80, 120), pain_overlay_alpha=65,
        win_bg=(235, 255, 252), win_left=(210, 255, 248),
        win_accent=(0, 160, 130), win_txt=(0, 90, 75),
        win_label="🎯  AI 自動化搞定", win_bullet="✦",
        win_overlay=(0, 100, 80), win_overlay_alpha=55,
        win_badge="省時又省力",
    ),
]

def _fetch_photo(category: str, w: int, h: int, cache_path: str, seed: int = 0) -> Image.Image | None:
    """從 Pexels 下載情境照片，每次根據 seed 選不同圖（不做長期 cache）"""
    import urllib3; urllib3.disable_warnings()

    # 每次重新下載（不 cache）確保每篇不同
    urls = PEXELS_PAIN if "pain" in category else PEXELS_WIN
    url  = urls[seed % len(urls)]

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Vivi-Agent/1.0)",
        "Accept": "image/jpeg,image/*",
    }
    try:
        resp = requests.get(url, timeout=20, verify=False,
                            allow_redirects=True, headers=headers)
        if resp.status_code == 200 and len(resp.content) > 20000:
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            img = img.resize((w, h), Image.LANCZOS)
            print(f"  📷 照片下載成功：{category} seed={seed}")
            return img
        else:
            print(f"  ⚠️ 照片 HTTP {resp.status_code}")
    except Exception as ex:
        print(f"  ⚠️ 照片下載失敗：{ex}")
    return None


def _photo_with_overlay(img: Image.Image, tw: int, th: int,
                         overlay_col: tuple, alpha: int = 140) -> Image.Image:
    """在照片上加半透明遮罩，讓文字更易讀"""
    img = img.resize((tw, th), Image.LANCZOS)
    overlay = Image.new("RGBA", (tw, th), overlay_col + (alpha,))
    base = img.convert("RGBA")
    merged = Image.alpha_composite(base, overlay)
    return merged.convert("RGB")


# ══════════════════════════════════════════════════════
# Hook clip（6 主題輪替版）
# ══════════════════════════════════════════════════════
def _hook_clip(pain_pts, win_pts, title, pain_audio, win_audio):
    pd = _audio_dur(pain_audio); wd = _audio_dur(win_audio)

    # ── 根據 title hash + 日期選主題與照片 seed（確保每篇不同）──
    import datetime as _dt, hashlib as _hl
    day_ord   = _dt.date.today().toordinal()
    title_h   = int(_hl.md5(title.encode()).hexdigest(), 16)
    combined  = day_ord ^ title_h

    theme_idx  = combined % len(HOOK_THEMES)
    pain_seed  = combined % len(PEXELS_PAIN)
    win_seed   = (combined + 4) % len(PEXELS_WIN)   # 偏移避免巧合同一張
    T = HOOK_THEMES[theme_idx]

    print(f"  🎨 Hook 主題 #{theme_idx}  痛點圖 seed={pain_seed}  成果圖 seed={win_seed}")

    pain_photo = _fetch_photo("pain", RW, AH, f"tmp_pain_{pain_seed}.jpg", seed=pain_seed)
    win_photo  = _fetch_photo("win",  RW, AH, f"tmp_win_{win_seed}.jpg",  seed=win_seed)

    # ══ Pain 幀 ══
    pi  = Image.new("RGB", (W, H), T["pain_bg"])
    pd2 = ImageDraw.Draw(pi)
    _top(pd2, title); _bot(pd2)

    pd2.rectangle([(0, AY), (LW+18, AB)], fill=T["pain_left"])

    # 左上標題區
    pd2.text((36, AY+22), T["pain_label"], font=_f(40, True), fill=T["pain_accent"])
    pd2.rectangle([(36, AY+74), (LW-18, AY+78)], fill=T["pain_accent"])

    # 痛點列表
    y = AY + 98
    for pt in pain_pts[:4]:
        _safe_text(pd2, (36, y), f"{T['pain_bullet']}  {pt}",
                   font=_f(30), fill=T["pain_txt"], max_width=LW-50)
        y += 58

    # 右側照片
    if pain_photo:
        ph = _photo_with_overlay(pain_photo, RW, AH,
                                  T["pain_overlay"], T["pain_overlay_alpha"])
        pi.paste(ph, (RX, AY))
        # 大 emoji / 符號疊加
        pd2.text((RX + RW//2 - 90, AY + AH//2 - 110),
                 "✗", font=_f(180, True), fill=(220, 30, 20))
    else:
        pd2.rectangle([(RX, AY), (W-12, AB)], fill=T["pain_left"])
        pd2.text((RX+40, AY+40), "收件匣：47 封未讀",
                 font=_f(36, True), fill=T["pain_accent"])

    pd2.rectangle([(RX-2, AY-2), (W-12, AB+2)],
                  outline=T["pain_accent"], width=5)
    pain_arr = np.array(pi)

    # ══ Win 幀 ══
    wi  = Image.new("RGB", (W, H), T["win_bg"])
    wd2 = ImageDraw.Draw(wi)
    _top(wd2, title); _bot(wd2)

    wd2.rectangle([(0, AY), (LW+18, AB)], fill=T["win_left"])

    wd2.text((36, AY+22), T["win_label"], font=_f(40, True), fill=T["win_accent"])
    wd2.rectangle([(36, AY+74), (LW-18, AY+78)], fill=T["win_accent"])

    y = AY + 98
    for wt in win_pts[:4]:
        _safe_text(wd2, (36, y), f"{T['win_bullet']}  {wt}",
                   font=_f(30), fill=T["win_txt"], max_width=LW-50)
        y += 58

    if win_photo:
        ph = _photo_with_overlay(win_photo, RW, AH,
                                  T["win_overlay"], T["win_overlay_alpha"])
        wi.paste(ph, (RX, AY))
        # 成果 badge
        badge = T["win_badge"]
        bw = wd2.textlength(badge, font=_f(38, True)) + 40
        bx = RX + (RW - bw) // 2
        by = AY + 24
        wd2.rectangle([(bx-4, by-4), (bx+bw+4, by+56)],
                       fill=T["win_accent"])
        wd2.text((bx+20, by+8), badge, font=_f(38, True), fill=(255, 255, 255))
    else:
        wd2.rectangle([(RX, AY), (W-12, AB)], fill=T["win_left"])
        wd2.text((RX+40, AY+40), T["win_badge"],
                 font=_f(40, True), fill=T["win_accent"])

    wd2.rectangle([(RX-2, AY-2), (W-12, AB+2)],
                  outline=T["win_accent"], width=5)
    win_arr = np.array(wi)

    pc = VideoClip(lambda t: pain_arr, duration=pd)
    wc = VideoClip(lambda t: win_arr,  duration=wd)
    if pain_audio and Path(pain_audio).exists(): pc = pc.set_audio(AudioFileClip(pain_audio))
    if win_audio  and Path(win_audio).exists():  wc = wc.set_audio(AudioFileClip(win_audio))
    return concatenate_videoclips([pc, wc], method="compose")

# ══════════════════════════════════════════════════════
# Step clip（打字動畫 + 輸出串流，支援簡報預覽）
# ══════════════════════════════════════════════════════
def _step_clip(step, title, total, type_audio, out_audio):
    td = _audio_dur(type_audio); od = _audio_dur(out_audio)
    num    = step.get("num", 1)
    head   = step.get("heading", "")
    bulls  = step.get("bullets") or []
    action = step.get("action_label", "")
    tool   = step.get("tool_name", "Claude")
    prompt = step.get("example_prompt", "").strip()
    output = step.get("example_output") or []
    tip    = step.get("tip", "")
    out_text = "\n".join(output)

    # 判斷是否為簡報步驟
    is_slide_step = step.get("is_slide_step", False) or \
                    any(k in tool.lower() for k in ["gamma","簡報","slide","canva"]) or \
                    any(k in head for k in ["簡報","投影","Gamma","slide"])

    # ── 靜態左側 ──
    base = Image.new("RGB", (W,H), C["bg"])
    bd   = ImageDraw.Draw(base)
    _top(bd, title); _bot(bd, action, num, total)
    bd.rectangle([(0,AY),(LW+18,AB)], fill=C["lbg"])
    bd.rectangle([(LW+16,AY),(LW+22,AB)], fill=C["sep"])
    cx, cy, r = 74, AY+62, 38
    bd.ellipse([(cx-r,cy-r),(cx+r,cy+r)], fill=C["accent"])
    nw = bd.textlength(str(num), font=_f(40,True))
    bd.text((cx-nw//2, cy-24), str(num), font=_f(40,True), fill=(255,255,255))
    fh = _f(50,True); hw = bd.textlength(head, font=fh)
    fh = _f(40,True) if hw > LW-36 else fh
    _safe_text(bd, (30, AY+112), head, font=fh, fill=C["hd"], max_width=LW-36)
    bd.rectangle([(30, AY+184),(LW-8, AY+188)], fill=C["sep"])
    y = AY + 204
    for i, b in enumerate(bulls[:3]):
        tw2 = bd.textlength(f"0{i+1}", font=_f(15,True))
        bd.rectangle([(30,y+2),(30+32,y+32)], fill=C["accent"])
        bd.text((30+(32-tw2)//2, y+7), f"0{i+1}", font=_f(15,True), fill=(255,255,255))
        _safe_text(bd, (70, y+4), b, font=_f(28), fill=C["bd"], max_width=LW-80); y += 54
    if tip and y < AB-60:
        bd.rectangle([(22,y+8),(LW-4,y+52)], fill=C["acdk"])
        _safe_text(bd, (36, y+16), f"💡 {tip}", font=_f(22), fill=(255,215,135), max_width=LW-48)
    base_arr = np.array(base)

    # ── 右側動態渲染 ──
    PAD=14; BAR=44; LBL=26
    pwl = []
    for seg in prompt.split("\n"):
        pwl += (textwrap.wrap(seg, width=33) or [""])
    PH = max(len(pwl)*29+16, 68)

    # 計算輸出框 y，加入保護
    OUT_Y = AY + BAR + PAD + LBL + 6 + PH + PAD + LBL + 6
    OUT_BOTTOM = AB - PAD
    OUT_VALID = OUT_Y < OUT_BOTTOM - 40  # 至少要有 40px 空間

    # 如果是簡報步驟，預先生成投影片預覽
    slide_img = None
    if is_slide_step:
        outline_items = [l for l in output if l and not l.startswith("【")]
        slide_img = _render_slide_preview(outline_items[:5], title, RW, AH)

    def _R(arr, sp, so, dots, show_slide=False):
        img2 = Image.fromarray(arr.copy())
        d2   = ImageDraw.Draw(img2)
        rx   = RX
        use_claude_ui = any(k in tool.lower() for k in ["claude","anthropic"])
        if use_claude_ui and not show_slide:
            clean_sp = sp.replace("\u25ae","")
            out_list = [l for l in so.split("\n") if l] if so else []
            all_chars = sum(len(l) for l in out_list)
            all_total = sum(len(l) for l in out_text.split("\n") if l)
            ratio = min(1.0, all_chars/max(all_total,1)) if so else 0.0
            cl_img = _render_claude_ui(RW, AH, clean_sp, out_list, ratio, dots)
            img2.paste(cl_img, (rx, AY))
            d2 = ImageDraw.Draw(img2)
            d2.rectangle([(rx-2,AY-2),(W-10,AB+2)], outline=C["sep"], width=3)
            return np.array(img2)
        # Chat 背景（非 Claude 工具）
        d2.rectangle([(rx,AY),(W-12,AB)], fill=C["cbg"])
        # Tool bar
        d2.rectangle([(rx,AY),(W-12,AY+BAR)], fill=C["tbar"])
        for cx2, col in [(rx+13,"#FF5F57"),(rx+29,"#FEBC2E"),(rx+45,"#28C840")]:
            d2.ellipse([(cx2-5,AY+16),(cx2+5,AY+26)], fill=col)
        d2.text((rx+60, AY+10), tool, font=_f(22,True), fill=(210,180,128))

        y2 = AY + BAR + PAD

        # Prompt label & box
        d2.rectangle([(rx+PAD,y2),(W-22,y2+LBL)], fill=C["lbl"])
        d2.text((rx+PAD+7, y2+4), "✏️  你輸入的指令", font=_f(15), fill=C["lblf"])
        y2 += LBL + 6
        y2_end = min(y2+PH, AB-PAD-80)  # 保護：不超過畫面
        if y2 < y2_end:
            d2.rectangle([(rx+PAD,y2),(W-22,y2_end)],
                         fill=C["pbg"], outline="#9ED09E", width=2)
            py2 = y2 + 8
            for line in sp.split("\n"):
                for wl in (textwrap.wrap(line, width=32) or [line]):
                    if py2 + 29 > y2_end: break
                    d2.text((rx+PAD+8, py2), wl, font=_f(20), fill=C["pfg"])
                    py2 += 29
        y2 = y2_end + PAD

        # Output label & box
        if y2 + LBL + 40 > AB - PAD:
            d2.rectangle([(rx-2,AY-2),(W-10,AB+2)], outline=C["sep"], width=3)
            return np.array(img2)

        d2.rectangle([(rx+PAD,y2),(W-22,y2+LBL)], fill=C["lbl"])
        if is_slide_step:
            d2.text((rx+PAD+7, y2+4), "🖼️  AI 生成的簡報", font=_f(15), fill=C["lblf"])
        else:
            d2.text((rx+PAD+7, y2+4), "🤖  AI 輸出結果", font=_f(15), fill=C["lblf"])
        y2 += LBL + 6

        out_top    = y2
        out_bottom = AB - PAD
        if out_top >= out_bottom:  # 保護
            d2.rectangle([(rx-2,AY-2),(W-10,AB+2)], outline=C["sep"], width=3)
            return np.array(img2)

        if show_slide and slide_img is not None:
            # 貼投影片預覽
            sl_h = out_bottom - out_top
            sl_resized = slide_img.resize((RW-PAD*2, sl_h), Image.LANCZOS)
            img2.paste(sl_resized, (rx+PAD, out_top))
            d2 = ImageDraw.Draw(img2)
            d2.rectangle([(rx+PAD-1,out_top-1),(W-22,out_bottom+1)],
                         outline=(92,60,220), width=2)
        elif dots >= 0:
            d2.rectangle([(rx+PAD,out_top),(W-22,out_bottom)],
                         fill=C["obg"], outline="#C8B870", width=2)
            dc = "●"*dots + "○"*(3-dots)
            d2.text((rx+PAD+10, out_top+10),
                    f"AI 生成中  {dc}", font=_f(24), fill=C["think"])
        else:
            d2.rectangle([(rx+PAD,out_top),(W-22,out_bottom)],
                         fill=C["obg"], outline="#C8B870", width=2)
            oy = out_top + 8
            for line in so.split("\n"):
                if oy + 28 > out_bottom - 6: break
                col = C["acdk2"] if line.startswith(
                    ("•","【","✅","⚠️","→","—","📌","💡","第","0","1","2","3")) else C["ofg"]
                d2.text((rx+PAD+10, oy), line[:38], font=_f(20), fill=col)
                oy += 28

        d2.rectangle([(rx-2,AY-2),(W-10,AB+2)], outline=C["sep"], width=3)
        return np.array(img2)

    # Typing clip
    def tf(t):
        p = t/td; n = int(p*len(prompt))
        cur = "▋" if int(t/0.5)%2==0 else ""
        return _R(base_arr, prompt[:n]+cur, "", -2)

    # Output clip
    T_THINK = 0.20
    def of(t):
        p = t/od
        if p < T_THINK:
            return _R(base_arr, prompt, "", int((p/T_THINK)*4)%4)
        op = (p-T_THINK)/(1-T_THINK)
        if is_slide_step and op > 0.3:
            return _R(base_arr, prompt, out_text, -1, show_slide=True)
        n = int(op*len(out_text))
        return _R(base_arr, prompt, out_text[:n], -1)

    tc = VideoClip(tf, duration=td)
    oc = VideoClip(of, duration=od)
    if type_audio and Path(type_audio).exists(): tc = tc.set_audio(AudioFileClip(type_audio))
    if out_audio  and Path(out_audio).exists():  oc = oc.set_audio(AudioFileClip(out_audio))
    return concatenate_videoclips([tc, oc], method="compose")

# ══════════════════════════════════════════════════════
# CTA
# ══════════════════════════════════════════════════════
def _cta_clip(title, cta_audio):
    dur = _audio_dur(cta_audio)
    img = Image.new("RGB",(W,H),C["bg"]); d = ImageDraw.Draw(img)
    _top(d, title); _bot(d)
    d.rectangle([(110,H//2-3),(W-110,H//2+1)], fill=C["sep"])
    for txt, sz, bold, yo in [
        ("🔔  訂閱 Vivi AI研習社，每週更新職場 AI 實戰", 50, True, -68),
        ("👇  留言你想學的工具，我下週教你", 40, False, 28),
    ]:
        tw = d.textlength(txt, font=_f(sz,bold))
        d.text(((W-tw)//2, H//2+yo), txt, font=_f(sz,bold),
               fill=C["hd"] if bold else C["bd"])
    arr = np.array(img)
    clip = VideoClip(lambda t: arr, duration=dur)
    if cta_audio and Path(cta_audio).exists(): clip = clip.set_audio(AudioFileClip(cta_audio))
    return clip

# ══════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════
def render_tutorial_video(segments: dict, steps: list,
                          title: str = "", output: str = "video_final.mp4") -> str:
    print(f"  🎬 渲染：{title}")
    pain_pts = steps[0].get("pain_points", []) if steps else []
    win_pts  = steps[0].get("win_points", [])  if steps else []

    clips = []
    clips.append(_hook_clip(pain_pts, win_pts, title,
                             segments.get("pain",""), segments.get("win","")))
    print("  ✅ Hook（Unsplash 封面照片）")

    for i, step in enumerate(steps, 1):
        clips.append(_step_clip(step, title, len(steps),
                                segments.get(f"step{i}_type",""),
                                segments.get(f"step{i}_out","")))
        tag = "🖼️ 簡報預覽" if step.get("is_slide_step") else "⌨️ 打字動畫"
        print(f"  ✅ Step {i} [{tag}]")

    clips.append(_cta_clip(title, segments.get("cta","")))
    print("  ✅ CTA")

    final = concatenate_videoclips(clips, method="compose")
    # 確保輸出是正確的 1920x1080（moviepy size 參數不可靠，改用 resize）
    if final.w != W or final.h != H:
        print(f"  ⚠️ 尺寸錯誤 {final.w}x{final.h}，強制 resize 至 {W}x{H}")
        final = final.resize((W, H))
    final.write_videofile(output, fps=FPS, codec="libx264",
                          audio_codec="aac", preset="fast", logger=None)
    dur  = sum(c.duration for c in clips)
    size = Path(output).stat().st_size // (1024*1024)
    print(f"  ✅ {output} | {dur:.0f}s | {size} MB")
    return output
