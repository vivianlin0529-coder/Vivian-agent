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
# ══════════════════════════════════════════════════════
# 照片庫 — 依主題分類（辦公室情境，無 X 標示）
# ══════════════════════════════════════════════════════

# 通用痛點（壓力/忙碌辦公室）
PHOTOS_PAIN_GENERAL = [
    "https://images.pexels.com/photos/5699678/pexels-photo-5699678.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/4101143/pexels-photo-4101143.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3760810/pexels-photo-3760810.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3799832/pexels-photo-3799832.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/4491461/pexels-photo-4491461.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/1496193/pexels-photo-1496193.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3184418/pexels-photo-3184418.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/7688336/pexels-photo-7688336.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3184339/pexels-photo-3184339.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/4386373/pexels-photo-4386373.jpeg?auto=compress&cs=tinysrgb&w=1920",
]
# 通用成果（成功/協作/效率）
PHOTOS_WIN_GENERAL = [
    "https://images.pexels.com/photos/3184291/pexels-photo-3184291.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3182812/pexels-photo-3182812.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/5255215/pexels-photo-5255215.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3184360/pexels-photo-3184360.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3184465/pexels-photo-3184465.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/1181354/pexels-photo-1181354.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3184433/pexels-photo-3184433.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/7688160/pexels-photo-7688160.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3183197/pexels-photo-3183197.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3184287/pexels-photo-3184287.jpeg?auto=compress&cs=tinysrgb&w=1920",
]
# 主題特化：簡報/投影片
PHOTOS_SLIDES = [
    "https://images.pexels.com/photos/3184325/pexels-photo-3184325.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3182773/pexels-photo-3182773.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/1181396/pexels-photo-1181396.jpeg?auto=compress&cs=tinysrgb&w=1920",
]
# 主題特化：Email/信件
PHOTOS_EMAIL = [
    "https://images.pexels.com/photos/4050290/pexels-photo-4050290.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/6238120/pexels-photo-6238120.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/4050287/pexels-photo-4050287.jpeg?auto=compress&cs=tinysrgb&w=1920",
]
# 主題特化：會議/討論
PHOTOS_MEETING = [
    "https://images.pexels.com/photos/3184317/pexels-photo-3184317.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/3182743/pexels-photo-3182743.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/1181622/pexels-photo-1181622.jpeg?auto=compress&cs=tinysrgb&w=1920",
]
# 主題特化：數據/報告
PHOTOS_DATA = [
    "https://images.pexels.com/photos/590022/pexels-photo-590022.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/669615/pexels-photo-669615.jpeg?auto=compress&cs=tinysrgb&w=1920",
    "https://images.pexels.com/photos/6801648/pexels-photo-6801648.jpeg?auto=compress&cs=tinysrgb&w=1920",
]

# 已用照片記錄（跨天避免重複）
USED_PHOTOS_FILE = "used_photos.json"

def _load_used_photos() -> set:
    from pathlib import Path as _P; import json as _j
    if not _P(USED_PHOTOS_FILE).exists(): return set()
    try:
        with open(USED_PHOTOS_FILE, encoding="utf-8") as f:
            rec = _j.load(f)
        import datetime as _d
        cutoff = (_d.datetime.now() - _d.timedelta(days=30)).isoformat()
        return {r["url"] for r in rec if r.get("date","") >= cutoff}
    except: return set()

def _save_used_photos(urls: list):
    import json as _j, datetime as _d
    records = []
    from pathlib import Path as _P
    if _P(USED_PHOTOS_FILE).exists():
        try:
            with open(USED_PHOTOS_FILE, encoding="utf-8") as f:
                records = _j.load(f)
        except: pass
    now = _d.datetime.now().isoformat()
    for u in urls:
        records.append({"url": u, "date": now})
    records = records[-200:]
    with open(USED_PHOTOS_FILE, "w", encoding="utf-8") as f:
        _j.dump(records, f, ensure_ascii=False, indent=2)

def _pick_photo_url(pool: list, seed: int, used: set) -> str:
    """從 pool 中依 seed 選出未用過的圖，沒有時允許重用最舊的"""
    fresh = [u for u in pool if u not in used]
    if not fresh:
        fresh = pool  # 全用完則重頭開始
    return fresh[seed % len(fresh)]

def _topic_photo_pools(title: str):
    """依選題關鍵字選擇對應照片池"""
    t = title.lower()
    if any(k in t for k in ["簡報","投影","gamma","canva","slide","ppt"]):
        return PHOTOS_SLIDES + PHOTOS_WIN_GENERAL, PHOTOS_SLIDES + PHOTOS_WIN_GENERAL
    if any(k in t for k in ["信件","email","mail","gmail","收件"]):
        return PHOTOS_EMAIL + PHOTOS_PAIN_GENERAL, PHOTOS_EMAIL + PHOTOS_WIN_GENERAL
    if any(k in t for k in ["會議","討論","meeting","記錄","逐字"]):
        return PHOTOS_MEETING + PHOTOS_PAIN_GENERAL, PHOTOS_MEETING + PHOTOS_WIN_GENERAL
    if any(k in t for k in ["報告","數據","data","分析","圖表","週報"]):
        return PHOTOS_DATA + PHOTOS_PAIN_GENERAL, PHOTOS_DATA + PHOTOS_WIN_GENERAL
    return PHOTOS_PAIN_GENERAL, PHOTOS_WIN_GENERAL


def _fetch_photo_url(url: str, w: int, h: int) -> "Image.Image | None":
    """下載單張照片"""
    import urllib3; urllib3.disable_warnings()
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "image/jpeg,image/*"}
    try:
        resp = requests.get(url, timeout=20, verify=False,
                            allow_redirects=True, headers=headers)
        if resp.status_code == 200 and len(resp.content) > 20000:
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            return img.resize((w, h), Image.LANCZOS)
        print(f"  ⚠️ 照片 HTTP {resp.status_code}")
    except Exception as ex:
        print(f"  ⚠️ 照片下載失敗：{ex}")
    return None


def _overlay(img: Image.Image, col: tuple, alpha: int) -> Image.Image:
    ov = Image.new("RGBA", img.size, col + (alpha,))
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


# ══════════════════════════════════════════════════════
# 10 種 Hook 版型繪製器（PPT多樣版型，每種架構完全不同）
# ══════════════════════════════════════════════════════

def _draw_layout(layout_id, pain_img, win_img, pain_pts, win_pts, title):
    """依 layout_id 繪製 pain 和 win 兩張靜態圖，回傳 (pain_arr, win_arr)"""

    # ── 通用輔助 ──────────────────────────────
    def _make(bg): 
        img = Image.new("RGB", (W, H), bg)
        d = ImageDraw.Draw(img)
        _top(d, title); _bot(d)
        return img, d

    def _pts(d, pts, x, y, bullet, accent, txt_col, size=30, spacing=56, maxw=600):
        for p in pts[:4]:
            _safe_text(d, (x, y), f"{bullet}  {p}", font=_f(size), fill=txt_col, max_width=maxw)
            y += spacing
        return y

    def _badge(d, text, cx, cy, bg, fg, pad=20):
        tw2 = d.textlength(text, font=_f(36, True))
        x0 = cx - tw2//2 - pad; y0 = cy - 28
        d.rectangle([(x0, y0), (x0+tw2+pad*2, y0+58)], fill=bg)
        d.text((x0+pad, y0+10), text, font=_f(36, True), fill=fg)

    # ── Layout 0：左文右照（改良版，無 X，accent border）──────────
    if layout_id == 0:
        RED=(195,35,18); GRN=(18,132,38)
        pi, pd_ = _make((255,242,240))
        pd_.rectangle([(0,AY),(LW+18,AB)], fill=(255,224,220))
        pd_.text((36,AY+22), "⚠  工作中的你", font=_f(40,True), fill=RED)
        pd_.rectangle([(36,AY+72),(LW-18,AY+76)], fill=RED)
        _pts(pd_, pain_pts, 36, AY+96, "—", RED, (100,30,20))
        if pain_img:
            pi.paste(_overlay(pain_img,(120,15,5),45), (RX,AY))
        pd_.rectangle([(RX-2,AY-2),(W-12,AB+2)], outline=RED, width=5)
        wi, wd_ = _make((240,252,244))
        wd_.rectangle([(0,AY),(LW+18,AB)], fill=(218,248,224))
        wd_.text((36,AY+22), "✓  用 AI 之後", font=_f(40,True), fill=GRN)
        wd_.rectangle([(36,AY+72),(LW-18,AY+76)], fill=GRN)
        _pts(wd_, win_pts, 36, AY+96, "→", GRN, (12,64,18))
        if win_img:
            wi.paste(_overlay(win_img,(8,55,18),50), (RX,AY))
            _badge(wd_, "AI 30秒搞定", RX+RW//2, AY+50, GRN, (255,255,255))
        wd_.rectangle([(RX-2,AY-2),(W-12,AB+2)], outline=GRN, width=5)
        return np.array(pi), np.array(wi)

    # ── Layout 1：全幅照片底圖 + 半透明文字卡 ──────────────────
    if layout_id == 1:
        BLUE=(20,60,180); LBLUE=(0,120,210)
        pi = Image.new("RGB", (W,H), (230,235,252))
        if pain_img:
            pi.paste(_overlay(pain_img,(10,20,80),120), (0,0))
        pd_ = ImageDraw.Draw(pi)
        _top(pd_, title); _bot(pd_)
        # 左側半透明卡
        card = Image.new("RGBA",(680,AH-20),(255,255,255,200))
        pi = Image.alpha_composite(pi.convert("RGBA"), Image.new("RGBA",(W,H),(0,0,0,0)))
        pi.paste(card, (20, AY+10), card)
        pi = pi.convert("RGB"); pd_ = ImageDraw.Draw(pi)
        _top(pd_, title); _bot(pd_)
        pd_.text((48,AY+36), "📊 你每天浪費多少時間？", font=_f(38,True), fill=BLUE)
        pd_.rectangle([(48,AY+88),(660,AY+92)], fill=BLUE)
        _pts(pd_, pain_pts, 48, AY+106, "▶", BLUE, (20,40,120), size=29, spacing=54, maxw=580)
        wi = Image.new("RGB", (W,H), (230,245,255))
        if win_img:
            wi.paste(_overlay(win_img,(0,50,110),110), (0,0))
        wd_ = ImageDraw.Draw(wi)
        _top(wd_, title); _bot(wd_)
        card2 = Image.new("RGBA",(680,AH-20),(255,255,255,200))
        wi = Image.alpha_composite(wi.convert("RGBA"), Image.new("RGBA",(W,H),(0,0,0,0)))
        wi.paste(card2, (20,AY+10), card2)
        wi = wi.convert("RGB"); wd_ = ImageDraw.Draw(wi)
        _top(wd_, title); _bot(wd_)
        wd_.text((48,AY+36), "🚀 AI 接手之後", font=_f(38,True), fill=LBLUE)
        wd_.rectangle([(48,AY+88),(660,AY+92)], fill=LBLUE)
        _pts(wd_, win_pts, 48, AY+106, "▶", LBLUE, (0,70,140), size=29, spacing=54, maxw=580)
        _badge(wd_, "效率直接翻倍", 340, AY+AH-70, LBLUE, (255,255,255))
        return np.array(pi), np.array(wi)

    # ── Layout 2：右文左照（反轉）+ 橙色主題 ──────────────────
    if layout_id == 2:
        ORG=(200,80,0); YLW=(180,130,0)
        LPH = W - RX - 14   # 左側寬度（照片）
        RPX = LPH + 20       # 右側文字起點
        RPW = W - RPX - 20
        pi, pd_ = _make((255,246,235))
        if pain_img:
            ph = pain_img.resize((LPH, AH), Image.LANCZOS)
            pi.paste(_overlay(ph,(140,50,0),60), (0,AY))
        pd_.rectangle([(RPX,AY),(W-8,AB)], fill=(255,232,210))
        pd_.text((RPX+20,AY+22), "🔥 Deadline", font=_f(44,True), fill=ORG)
        pd_.text((RPX+20,AY+72), "壓力山大", font=_f(36,True), fill=ORG)
        pd_.rectangle([(RPX+20,AY+118),(W-28,AY+122)], fill=ORG)
        _pts(pd_, pain_pts, RPX+20, AY+136, "!", ORG, (120,50,0), size=27, spacing=52, maxw=RPW-30)
        pd_.rectangle([(LPH-2,AY-2),(LPH+2,AB+2)], fill=ORG, )
        wi, wd_ = _make((255,252,235))
        if win_img:
            wh = win_img.resize((LPH, AH), Image.LANCZOS)
            wi.paste(_overlay(wh,(110,80,0),50), (0,AY))
        wd_.rectangle([(RPX,AY),(W-8,AB)], fill=(255,250,215))
        wd_.text((RPX+20,AY+22), "⚡ AI 加速", font=_f(44,True), fill=YLW)
        wd_.text((RPX+20,AY+72), "準時交件", font=_f(36,True), fill=YLW)
        wd_.rectangle([(RPX+20,AY+118),(W-28,AY+122)], fill=YLW)
        _pts(wd_, win_pts, RPX+20, AY+136, "★", YLW, (100,75,0), size=27, spacing=52, maxw=RPW-30)
        _badge(wd_, "不再趕 Deadline", RPX+RPW//2, AY+AH-70, YLW, (255,255,255))
        wd_.rectangle([(LPH-2,AY-2),(LPH+2,AB+2)], fill=YLW)
        return np.array(pi), np.array(wi)

    # ── Layout 3：上下分割 — 照片上半，文字下半 ──────────────────
    if layout_id == 3:
        PUR=(120,30,190); TEAL=(0,160,130)
        MID = AY + (AB-AY)//2
        pi, pd_ = _make((245,238,255))
        if pain_img:
            ph = pain_img.resize((W, MID-AY), Image.LANCZOS)
            pi.paste(_overlay(ph,(80,10,140),80), (0,AY))
        pd_.rectangle([(0,MID),(W,AB)], fill=(235,220,255))
        pd_.text((40,MID+16), "😩  你卡關的地方", font=_f(38,True), fill=PUR)
        pd_.rectangle([(40,MID+62),(W-40,MID+66)], fill=PUR)
        # 橫排 2x2 痛點
        pts2 = pain_pts[:4]
        col_w = (W-80)//2
        for i, p in enumerate(pts2):
            cx2 = 40 + (i%2)*col_w; cy2 = MID+80 + (i//2)*58
            _safe_text(pd_, (cx2,cy2), f"— {p}", font=_f(28), fill=(70,15,120), max_width=col_w-20)
        wi, wd_ = _make((235,252,248))
        if win_img:
            wh = win_img.resize((W, MID-AY), Image.LANCZOS)
            wi.paste(_overlay(wh,(0,100,80),70), (0,AY))
            _badge(wd_, "AI 一鍵解決", W//2, AY+(MID-AY)//2, TEAL, (255,255,255))
        wd_.rectangle([(0,MID),(W,AB)], fill=(215,248,240))
        wd_.text((40,MID+16), "✨  AI 之後的你", font=_f(38,True), fill=TEAL)
        wd_.rectangle([(40,MID+62),(W-40,MID+66)], fill=TEAL)
        col_w2 = (W-80)//2
        for i, p in enumerate(win_pts[:4]):
            cx2 = 40 + (i%2)*col_w2; cy2 = MID+80 + (i//2)*58
            _safe_text(wd_, (cx2,cy2), f"→ {p}", font=_f(28), fill=(0,90,75), max_width=col_w2-20)
        return np.array(pi), np.array(wi)

    # ── Layout 4：大數字衝擊 — 中央數字 + 兩側文字 ──────────────
    if layout_id == 4:
        NAVY=(15,35,120); GOLD=(190,140,20)
        pi, pd_ = _make((235,240,255))
        if pain_img:
            pi.paste(_overlay(pain_img,(10,20,90),140), (0,AY))
        pd_ = ImageDraw.Draw(pi); _top(pd_, title); _bot(pd_)
        # 中央大數字
        pd_.text((W//2-80, AY+40), "3h", font=_f(200,True), fill=(255,80,80,200))
        pd_.text((W//2-220, AY+240), "你每天花在這件事上的時間", font=_f(32,True), fill=(255,255,255))
        # 左右痛點（覆蓋在照片上）
        for i,p in enumerate(pain_pts[:2]):
            _safe_text(pd_, (40, AY+120+i*70), f"—  {p}", font=_f(30,True), fill=(255,220,200), max_width=400)
        for i,p in enumerate(pain_pts[2:4]):
            _safe_text(pd_, (W-460, AY+120+i*70), f"—  {p}", font=_f(30,True), fill=(255,220,200), max_width=400)
        wi, wd_ = _make((230,245,255))
        if win_img:
            wi.paste(_overlay(win_img,(0,40,100),130), (0,AY))
        wd_ = ImageDraw.Draw(wi); _top(wd_, title); _bot(wd_)
        wd_.text((W//2-130, AY+40), "30s", font=_f(180,True), fill=(80,255,160,200))
        wd_.text((W//2-220, AY+230), "AI 完成同樣工作只需要", font=_f(32,True), fill=(255,255,255))
        for i,p in enumerate(win_pts[:2]):
            _safe_text(wd_, (40, AY+120+i*70), f"→  {p}", font=_f(30,True), fill=(180,255,210), max_width=400)
        for i,p in enumerate(win_pts[2:4]):
            _safe_text(wd_, (W-460, AY+120+i*70), f"→  {p}", font=_f(30,True), fill=(180,255,210), max_width=400)
        return np.array(pi), np.array(wi)

    # ── Layout 5：黑金質感 — 深色底，金色文字 ──────────────────
    if layout_id == 5:
        BG_D=(28,22,10); GLD=(206,158,68); LGLD=(245,210,120)
        pi, pd_ = _make(BG_D)
        pd_.rectangle([(0,AY),(W,AB)], fill=BG_D)
        if pain_img:
            ph = _overlay(pain_img,(28,22,10),170)
            pi.paste(ph.resize((RW,AH),Image.LANCZOS), (RX,AY))
        # 左側金色裝飾線
        pd_.rectangle([(40,AY+30),(44,AB-30)], fill=GLD)
        pd_.text((60,AY+30), "📌", font=_f(40), fill=GLD)
        pd_.text((60,AY+80), "職場痛點", font=_f(48,True), fill=GLD)
        pd_.rectangle([(60,AY+138),(LW-20,AY+142)], fill=GLD)
        _pts(pd_, pain_pts, 60, AY+158, "·", GLD, LGLD, size=30, spacing=56, maxw=LW-80)
        pd_.rectangle([(RX-2,AY-2),(W-12,AB+2)], outline=GLD, width=3)
        wi, wd_ = _make(BG_D)
        wd_.rectangle([(0,AY),(W,AB)], fill=BG_D)
        if win_img:
            wh = _overlay(win_img,(28,22,10),140)
            wi.paste(wh.resize((RW,AH),Image.LANCZOS), (RX,AY))
        wd_.rectangle([(40,AY+30),(44,AB-30)], fill=GLD)
        wd_.text((60,AY+30), "💼", font=_f(40), fill=GLD)
        wd_.text((60,AY+80), "AI 職場升級", font=_f(48,True), fill=GLD)
        wd_.rectangle([(60,AY+138),(LW-20,AY+142)], fill=GLD)
        _pts(wd_, win_pts, 60, AY+158, "◆", GLD, LGLD, size=30, spacing=56, maxw=LW-80)
        _badge(wd_, "職場競爭力 UP", RX+RW//2, AY+50, GLD, BG_D)
        wd_.rectangle([(RX-2,AY-2),(W-12,AB+2)], outline=GLD, width=3)
        return np.array(pi), np.array(wi)

    # ── Layout 6：青藍清新 — 圓角卡片，條列式 ──────────────────
    if layout_id == 6:
        TEAL=(0,140,180); MINT=(0,160,130)
        pi, pd_ = _make((230,248,255))
        if pain_img:
            pi.paste(_overlay(pain_img,(0,80,120),65).resize((RW,AH),Image.LANCZOS),(RX,AY))
        pd_.rectangle([(0,AY),(LW+18,AB)], fill=(208,240,255))
        pd_.text((36,AY+22), "😓 每天都在重複", font=_f(40,True), fill=TEAL)
        pd_.rectangle([(36,AY+72),(LW-18,AY+76)], fill=TEAL)
        _pts(pd_, pain_pts, 36, AY+96, "→", TEAL, (0,80,110), size=30, spacing=58, maxw=LW-50)
        pd_.rectangle([(RX-2,AY-2),(W-12,AB+2)], outline=TEAL, width=5)
        wi, wd_ = _make((225,255,250))
        if win_img:
            wi.paste(_overlay(win_img,(0,100,80),55).resize((RW,AH),Image.LANCZOS),(RX,AY))
        wd_.rectangle([(0,AY),(LW+18,AB)], fill=(205,248,238))
        wd_.text((36,AY+22), "🎯 AI 自動化搞定", font=_f(40,True), fill=MINT)
        wd_.rectangle([(36,AY+72),(LW-18,AY+76)], fill=MINT)
        _pts(wd_, win_pts, 36, AY+96, "✦", MINT, (0,90,75), size=30, spacing=58, maxw=LW-50)
        _badge(wd_, "省時又省力", RX+RW//2, AY+50, MINT, (255,255,255))
        wd_.rectangle([(RX-2,AY-2),(W-12,AB+2)], outline=MINT, width=5)
        return np.array(pi), np.array(wi)

    # ── Layout 7：卡片牆 — 4 格痛點卡片 ──────────────────────
    if layout_id == 7:
        PNK=(180,30,100); ROSE=(220,60,120)
        pi, pd_ = _make((255,235,245))
        if pain_img:
            pi.paste(_overlay(pain_img,(130,10,60),150).resize((W,H-TOP_H-BOT_H),Image.LANCZOS),(0,AY))
        pd_ = ImageDraw.Draw(pi); _top(pd_, title); _bot(pd_)
        pd_.text((W//2-200, AY+10), "📮 這些困擾你每天都有", font=_f(38,True), fill=(255,220,235))
        # 2x2 卡片
        CW=420; CH=200; GAP=20
        ox=(W-CW*2-GAP)//2; oy=AY+70
        for i, p in enumerate(pain_pts[:4]):
            cx2=ox+(i%2)*(CW+GAP); cy2=oy+(i//2)*(CH+GAP)
            pd_.rectangle([(cx2,cy2),(cx2+CW,cy2+CH)], fill=(255,255,255,200))
            pd_.rectangle([(cx2,cy2),(cx2+CW,cy2+8)], fill=PNK)
            _safe_text(pd_,(cx2+16,cy2+24), p, font=_f(30), fill=(100,20,60), max_width=CW-30)
        wi, wd_ = _make((235,255,250))
        if win_img:
            wi.paste(_overlay(win_img,(0,80,50),140).resize((W,H-TOP_H-BOT_H),Image.LANCZOS),(0,AY))
        wd_ = ImageDraw.Draw(wi); _top(wd_, title); _bot(wd_)
        TEAL2=(0,150,110)
        wd_.text((W//2-200, AY+10), "AI 幫你一次解決", font=_f(38,True), fill=(200,255,235))
        for i, p in enumerate(win_pts[:4]):
            cx2=ox+(i%2)*(CW+GAP); cy2=oy+(i//2)*(CH+GAP)
            wd_.rectangle([(cx2,cy2),(cx2+CW,cy2+CH)], fill=(255,255,255,210))
            wd_.rectangle([(cx2,cy2),(cx2+CW,cy2+8)], fill=TEAL2)
            _safe_text(wd_,(cx2+16,cy2+24), p, font=_f(30), fill=(0,80,55), max_width=CW-30)
        return np.array(pi), np.array(wi)

    # ── Layout 8：簡約留白 — 大字標題 + 細緻條列 ──────────────
    if layout_id == 8:
        IND=(40,40,160); SLATE=(80,80,120)
        pi, pd_ = _make((248,248,255))
        pd_.rectangle([(0,AY),(W,AY+12)], fill=IND)
        pd_.text((60,AY+30), "每天的", font=_f(52), fill=SLATE)
        pd_.text((60,AY+96), "時間黑洞", font=_f(80,True), fill=IND)
        pd_.rectangle([(60,AY+190),(500,AY+196)], fill=IND)
        _pts(pd_, pain_pts, 60, AY+216, "○", IND, SLATE, size=32, spacing=60, maxw=700)
        if pain_img:
            pi.paste(_overlay(pain_img,(40,40,140),70).resize((580,AH),Image.LANCZOS),(W-600,AY))
        wi, wd_ = _make((245,255,248))
        GRN2=(30,140,60); LGND=(80,160,100)
        wd_.rectangle([(0,AY),(W,AY+12)], fill=GRN2)
        wd_.text((60,AY+30), "AI 幫你", font=_f(52), fill=LGND)
        wd_.text((60,AY+96), "找回時間", font=_f(80,True), fill=GRN2)
        wd_.rectangle([(60,AY+190),(500,AY+196)], fill=GRN2)
        _pts(wd_, win_pts, 60, AY+216, "●", GRN2, LGND, size=32, spacing=60, maxw=700)
        if win_img:
            wi.paste(_overlay(win_img,(20,90,40),60).resize((580,AH),Image.LANCZOS),(W-600,AY))
        return np.array(pi), np.array(wi)

    # ── Layout 9：電影感橫幅 — 黑底白字+彩色accent ──────────────
    if layout_id == 9:
        BK=(18,18,18); WT=(245,245,245)
        # 隨機 accent（依 title hash）
        import hashlib as _hl
        hx=int(_hl.md5(title.encode()).hexdigest()[:4],16)
        accents=[(220,60,60),(60,140,220),(200,120,20),(140,60,200),(20,160,130)]
        ACC=accents[hx%len(accents)]
        pi, pd_ = _make(BK)
        pd_.rectangle([(0,AY),(W,AB)], fill=BK)
        if pain_img:
            pi.paste(_overlay(pain_img,BK,180).resize((W,AH),Image.LANCZOS),(0,AY))
        pd_ = ImageDraw.Draw(pi); _top(pd_, title); _bot(pd_)
        pd_.rectangle([(60,AY+30),(8,AY+30+AH-60)], fill=ACC)
        pd_.rectangle([(60,AY+36),(440,AY+40)], fill=ACC)
        pd_.text((80,AY+50), "痛點", font=_f(64,True), fill=ACC)
        _pts(pd_, pain_pts, 80, AY+128, "▸", ACC, WT, size=31, spacing=58, maxw=820)
        wi, wd_ = _make(BK)
        wd_.rectangle([(0,AY),(W,AB)], fill=BK)
        if win_img:
            wi.paste(_overlay(win_img,BK,150).resize((W,AH),Image.LANCZOS),(0,AY))
        wd_ = ImageDraw.Draw(wi); _top(wd_, title); _bot(wd_)
        wd_.rectangle([(60,AY+30),(8,AY+30+AH-60)], fill=ACC)
        wd_.rectangle([(60,AY+36),(440,AY+40)], fill=ACC)
        wd_.text((80,AY+50), "AI 解法", font=_f(64,True), fill=ACC)
        _pts(wd_, win_pts, 80, AY+128, "▸", ACC, WT, size=31, spacing=58, maxw=820)
        _badge(wd_, "立即試試看", W-300, AY+AH-70, ACC, BK)
        return np.array(pi), np.array(wi)

    # Fallback → Layout 0
    return _draw_layout(0, pain_img, win_img, pain_pts, win_pts, title)


# ══════════════════════════════════════════════════════
# Hook clip（10 版型 + 主題照片 + 無 X 標示）
# ══════════════════════════════════════════════════════
def _hook_clip(pain_pts, win_pts, title, pain_audio, win_audio):
    pd_ = min(_audio_dur(pain_audio), 3.5)   # 痛點最多3.5秒
    wd_ = min(_audio_dur(win_audio),  3.5)   # 成果最多3.5秒

    import datetime as _dt, hashlib as _hl
    day_ord   = _dt.date.today().toordinal()
    title_h   = int(_hl.md5(title.encode()).hexdigest(), 16)
    combined  = day_ord ^ title_h

    # 選 layout（10 種）— 優先讀視覺概念建議，否則用 hash 決定
    import os as _os
    override = _os.environ.get("HOOK_LAYOUT_OVERRIDE", "")
    layout_id = int(override) % 10 if override.isdigit() else combined % 10

    # 選主題照片池
    pain_pool, win_pool = _topic_photo_pools(title)
    used_photos = _load_used_photos()

    pain_url = _pick_photo_url(pain_pool, combined,   used_photos)
    win_url  = _pick_photo_url(win_pool,  combined+7, used_photos)

    print(f"  🎨 Hook 版型 #{layout_id}  痛點圖={pain_url[-30:]}  成果圖={win_url[-30:]}")

    pain_img = _fetch_photo_url(pain_url, RW, AH)
    win_img  = _fetch_photo_url(win_url,  RW, AH)

    # 記錄已用照片
    _save_used_photos([pain_url, win_url])

    pain_arr, win_arr = _draw_layout(layout_id, pain_img, win_img, pain_pts, win_pts, title)

    from moviepy.editor import AudioFileClip, VideoClip, concatenate_videoclips
    pc = VideoClip(lambda t: pain_arr, duration=pd_)
    wc = VideoClip(lambda t: win_arr,  duration=wd_)
    if pain_audio and Path(pain_audio).exists(): pc = pc.set_audio(AudioFileClip(pain_audio))
    if win_audio  and Path(win_audio).exists():  wc = wc.set_audio(AudioFileClip(win_audio))
    return concatenate_videoclips([pc, wc], method="compose")



# ══════════════════════════════════════════════════════
# Claude UI 渲染（Claude.ai 風格）
# ══════════════════════════════════════════════════════
def _render_claude_ui(pw: int, ph: int, prompt_text: str, out_lines: list,
                      ratio: float, dots: int) -> "Image.Image":
    """渲染 Claude.ai 風格聊天面板，返回 PIL Image (pw, ph)。"""
    BG         = (255, 253, 249)
    SIDEBAR_BG = (250, 247, 241)
    HUMAN_BG   = (237, 233, 225)
    CLAUDE_BG  = (255, 255, 255)
    CLAUDE_ORG = (217, 119, 87)
    TEXT_DK    = (25, 20, 15)
    TEXT_MD    = (80, 65, 50)
    TEXT_LT    = (140, 120, 100)
    SEP_COL    = (220, 210, 195)

    img = Image.new("RGB", (pw, ph), BG)
    d   = ImageDraw.Draw(img)

    # Top bar
    TB = 50
    d.rectangle([(0, 0), (pw, TB)], fill=SIDEBAR_BG)
    d.rectangle([(0, TB), (pw, TB + 2)], fill=SEP_COL)
    d.ellipse([(14, 12), (38, 38)], fill=CLAUDE_ORG)
    d.text((50, 12), "Claude", font=_f(28, True), fill=TEXT_DK)
    d.text((50 + int(d.textlength("Claude", font=_f(28, True))) + 10, 19),
           "claude.ai", font=_f(18), fill=TEXT_LT)

    PAD      = 18
    bx       = PAD + 16
    fnt_body = _f(22)
    avg_cw   = max(1, int(d.textlength("測", font=fnt_body)))
    bubble_w = pw - bx - PAD - 8
    wrap_w   = max(10, bubble_w // avg_cw)

    # Human message
    msg_top = TB + 18
    d.text((bx, msg_top), "你", font=_f(20, True), fill=CLAUDE_ORG)
    bubble_top = msg_top + 28
    lines_p = []
    for seg in (prompt_text or "").split("\n"):
        lines_p.extend(textwrap.wrap(seg, width=wrap_w) or [""])
    bubble_h = max(44, len(lines_p) * 29 + 16)
    bubble_bot = bubble_top + bubble_h
    d.rectangle([(bx, bubble_top), (bx + bubble_w, bubble_bot)],
                fill=HUMAN_BG, outline=SEP_COL, width=1)
    ty = bubble_top + 8
    for ln in lines_p:
        if ty + 27 > bubble_bot - 4: break
        d.text((bx + 10, ty), ln, font=fnt_body, fill=TEXT_DK)
        ty += 29

    # Divider
    div_y = bubble_bot + 16
    d.rectangle([(PAD, div_y), (pw - PAD, div_y + 1)], fill=SEP_COL)

    # Claude response
    resp_top = div_y + 18
    if resp_top + 30 > ph - PAD:
        return img
    d.text((bx, resp_top), "Claude", font=_f(20, True), fill=CLAUDE_ORG)
    resp_top += 30

    resp_bot = ph - PAD
    if resp_top >= resp_bot:
        return img

    if dots == -2:
        # 打字中：空白輸出區 + 游標
        d.rectangle([(bx, resp_top), (bx + bubble_w, min(resp_top + 46, resp_bot))],
                    fill=CLAUDE_BG, outline=SEP_COL, width=1)
        d.text((bx + 10, resp_top + 10), "▋", font=fnt_body, fill=TEXT_MD)
    elif dots >= 0:
        # 思考中
        d.rectangle([(bx, resp_top), (bx + bubble_w, min(resp_top + 46, resp_bot))],
                    fill=CLAUDE_BG, outline=SEP_COL, width=1)
        dc = "●" * dots + "○" * (3 - dots)
        d.text((bx + 10, resp_top + 10), f"思考中  {dc}", font=fnt_body, fill=TEXT_MD)
    else:
        # 輸出串流
        d.rectangle([(bx, resp_top), (bx + bubble_w, resp_bot)],
                    fill=CLAUDE_BG, outline=SEP_COL, width=1)
        oy = resp_top + 8
        max_lines = max(1, (resp_bot - resp_top - 12) // 29)
        for ln in (out_lines or [])[:max_lines]:
            if oy + 27 > resp_bot - 4: break
            col = CLAUDE_ORG if ln.startswith(
                ("•", "【", "✅", "⚠️", "→", "—", "📌", "💡",
                 "第", "0", "1", "2", "3", "4", "5")) else TEXT_DK
            while ln and d.textlength(ln, font=fnt_body) > bubble_w - 22:
                ln = ln[:-1]
            d.text((bx + 10, oy), ln, font=fnt_body, fill=col)
            oy += 29
        if ratio < 1.0 and oy + 27 < resp_bot - 4:
            d.text((bx + 10, oy), "▋", font=fnt_body, fill=TEXT_MD)
    return img


# ══════════════════════════════════════════════════════
# Gamma 風格投影片預覽渲染
# ══════════════════════════════════════════════════════
def _render_slide_preview(outline_items: list, title: str,
                          pw: int, ph: int) -> "Image.Image":
    """渲染 Gamma 風格投影片大綱預覽，返回 PIL Image (pw, ph)。"""
    SLIDE_BG   = (28, 22, 48)
    SLIDE_CARD = (44, 36, 68)
    SLIDE_ACC  = (92, 60, 220)
    SLIDE_FG   = (240, 235, 255)
    SLIDE_DIM  = (160, 145, 200)

    img = Image.new("RGB", (pw, ph), SLIDE_BG)
    d   = ImageDraw.Draw(img)

    # 標題列
    d.rectangle([(0, 0), (pw, 54)], fill=SLIDE_ACC)
    _safe_text(d, (16, 13), f"🎬 {title}", font=_f(24, True),
               fill=(255, 255, 255), max_width=pw - 32)

    # 投影片卡片
    PAD    = 14
    y      = 66
    n      = max(1, len(outline_items))
    card_h = max(38, (ph - 72 - PAD) // n - 8)
    for i, item in enumerate(outline_items):
        if y + card_h > ph - PAD: break
        d.rectangle([(PAD, y), (pw - PAD, y + card_h)],
                    fill=SLIDE_CARD, outline=SLIDE_ACC, width=2)
        NW = 32
        d.rectangle([(PAD, y), (PAD + NW, y + card_h)], fill=SLIDE_ACC)
        d.text((PAD + 7, y + card_h // 2 - 13), str(i + 1),
               font=_f(20, True), fill=(255, 255, 255))
        _safe_text(d, (PAD + NW + 10, y + card_h // 2 - 13), item,
                   font=_f(22), fill=SLIDE_FG,
                   max_width=pw - PAD * 2 - NW - 22)
        y += card_h + 8

    d.text((pw - 90, ph - 30), "Gamma ✦", font=_f(18), fill=SLIDE_DIM)
    return img



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
# Prompt 結尾頁（讓觀眾截圖下載套用）
# ══════════════════════════════════════════════════════
def _prompt_slide_clip(steps: list, title: str, duration: float = 6.0):
    """最後一頁：展示所有步驟的 Prompt，觀眾可截圖直接套用"""
    img = Image.new("RGB", (W, H), (18, 22, 38))   # 深藍底
    d   = ImageDraw.Draw(img)

    # 頂部標題列
    d.rectangle([(0,0),(W, TOP_H)], fill=(28, 35, 65))
    d.text((W//2 - 260, 18), "📋  本集 Prompt 完整版  複製即可用", font=_f(36, True), fill=(255, 210, 80))
    d.rectangle([(0, TOP_H),(W, TOP_H+3)], fill=(80, 100, 200))

    # 底部 CTA
    d.rectangle([(0, H-BOT_H),(W, H)], fill=(28, 35, 65))
    d.text((W//2 - 280, H-BOT_H+14), "🔔  訂閱 Vivi AI研習社  ·  每週更新職場 AI 實戰技巧", font=_f(28), fill=(180, 190, 220))

    # Prompt 卡片區（最多顯示3個步驟）
    card_colors = [(42, 55, 110), (35, 70, 60), (65, 42, 90)]
    accent_colors= [(100, 140, 255), (60, 200, 140), (180, 100, 255)]
    pad = 28
    card_h = (H - TOP_H - BOT_H - pad*4) // 3
    y = TOP_H + pad

    for i, step in enumerate(steps[:3]):
        ep = step.get("example_prompt", "").strip()
        heading = step.get("heading", f"Step {i+1}")
        num = step.get("num", i+1)
        acc = accent_colors[i % len(accent_colors)]
        cbg = card_colors[i % len(card_colors)]

        # 卡片背景
        d.rectangle([(pad, y),(W-pad, y+card_h)], fill=cbg)
        d.rectangle([(pad, y),(pad+6, y+card_h)], fill=acc)

        # Step 標題
        d.text((pad+18, y+10), f"Step {num}  {heading}", font=_f(28, True), fill=acc)
        d.rectangle([(pad+18, y+46),(W-pad-18, y+50)], fill=acc)

        # Prompt 文字（截斷顯示，最多4行）
        lines = ep.replace("\n", " ").split()
        wrapped = []
        current = ""
        for w2 in lines:
            test = current + " " + w2 if current else w2
            if d.textlength(test, font=_f(24)) < W - pad*3 - 20:
                current = test
            else:
                if current: wrapped.append(current)
                current = w2
        if current: wrapped.append(current)

        ty = y + 58
        for line in wrapped[:4]:
            if ty + 30 > y + card_h - 8: break
            d.text((pad+18, ty), line, font=_f(24), fill=(220, 225, 240))
            ty += 32

        y += card_h + pad

    arr = np.array(img)
    clip = VideoClip(lambda t: arr, duration=duration)
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

    clips.append(_prompt_slide_clip(steps, title, duration=7.0))
    print("  ✅ Prompt 結尾頁（可截圖套用）")

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
