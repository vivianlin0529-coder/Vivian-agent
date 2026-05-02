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
def _fetch_photo(query: str, w: int, h: int, cache_path: str) -> Image.Image | None:
    """從 Unsplash Source 抓免費高質照片（不需 API key）"""
    if Path(cache_path).exists():
        try:
            img = Image.open(cache_path).convert("RGB")
            print(f"  📷 使用快取照片：{cache_path}")
            return img
        except: pass
    try:
        # Unsplash Source API（免費）
        url = f"https://source.unsplash.com/{w}x{h}/?{query}"
        resp = requests.get(url, timeout=15, allow_redirects=True)
        if resp.status_code == 200 and len(resp.content) > 10000:
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            img.save(cache_path)
            print(f"  📷 下載照片成功：{cache_path} ({len(resp.content)//1024}KB)")
            return img
    except Exception as e:
        print(f"  ⚠️ 照片下載失敗：{e}")
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
# 簡報預覽圖（Gamma 風格，Step 3 專用）
# ══════════════════════════════════════════════════════
def _render_claude_ui(tw, th, prompt, output_lines, stream_ratio=1.0, thinking_dots=-1):
    """真實 claude.ai 風格對話 UI"""
    img  = Image.new("RGB", (tw, th), (255,255,255))
    draw = ImageDraw.Draw(img)
    SIDE_W = 196
    # 左側欄
    draw.rectangle([(0,0),(SIDE_W,th)], fill=(30,27,23))
    draw.text((14,14), "\u2736", font=_f(28,True), fill=(255,200,100))
    draw.text((44,18), "Claude", font=_f(22,True), fill=(230,220,200))
    draw.rounded_rectangle([(10,56),(SIDE_W-10,86)], radius=8,
                            fill=(50,44,36), outline=(80,70,55), width=1)
    draw.text((18,64), "\u270f  New chat", font=_f(17), fill=(200,185,160))
    draw.text((14,106), "Today", font=_f(13), fill=(110,100,80))
    for i, h in enumerate(["Meeting notes", "Email draft", "Report summary"]):
        draw.text((14, 124+i*28), h, font=_f(14), fill=(148,136,115))
    # 主區
    CX = SIDE_W
    draw.rectangle([(CX,0),(tw,48)], fill=(252,251,249))
    draw.rectangle([(CX,47),(tw,48)], fill=(218,212,200))
    draw.text((CX+18,14), "claude-sonnet-4-5  \u25be", font=_f(17), fill=(100,88,68))
    draw.rectangle([(CX,48),(tw,th)], fill=(252,251,249))
    # 使用者訊息氣泡
    msg_lines = []
    for seg in (prompt or "").replace("\u25ae","").split("\n"):
        msg_lines += (textwrap.wrap(seg, width=30) or [""])
    msg_lines = [l for l in msg_lines if l][:5]
    MSG_H = len(msg_lines)*27+18; MSG_W = min(tw-CX-70, 480)
    MSG_X = tw - MSG_W - 20; MSG_Y = 60
    draw.rounded_rectangle([(MSG_X,MSG_Y),(tw-20,MSG_Y+MSG_H)],
                            radius=12, fill=(232,226,214))
    my = MSG_Y+9
    for line in msg_lines:
        draw.text((MSG_X+12,my), line, font=_f(19), fill=(48,36,20)); my+=27
    # Claude 回覆
    RY = MSG_Y + MSG_H + 24
    draw.ellipse([(CX+18,RY),(CX+40,RY+22)], fill=(195,135,55))
    draw.text((CX+25,RY+2), "\u2736", font=_f(14,True), fill="white")
    draw.text((CX+48,RY+4), "Claude", font=_f(16,True), fill=(75,60,38))
    TY = RY+30; MAX_Y = th-72
    if thinking_dots >= 0:
        dc = "\u25cf"*thinking_dots+"\u25cb"*(3-thinking_dots)
        draw.text((CX+22,TY), "  "+dc, font=_f(26), fill=(155,135,95))
    else:
        total = sum(len(l) for l in output_lines)
        shown_ch = int(total*stream_ratio); remain = shown_ch
        sl = []
        for line in output_lines:
            if remain<=0: break
            sl.append(line[:remain]); remain -= len(line)
        ry2 = TY
        for line in sl:
            if ry2+27>MAX_Y: break
            is_h = line.startswith(("\u3010","\u2022","\u2192","\u2705","\ud83d","\u7b2c","*"))
            draw.text((CX+22,ry2), line[:40], font=_f(19,is_h),
                      fill=(45,30,10) if is_h else (65,50,30))
            ry2+=27
        if stream_ratio<1.0 and sl:
            cx3=CX+22+draw.textlength(sl[-1][:40],font=_f(19))
            if ry2-27+2<MAX_Y:
                draw.rectangle([(cx3+2,ry2-25),(cx3+9,ry2-4)], fill=(155,80,35))
    # 底部輸入
    IY = th-64
    draw.rounded_rectangle([(CX+14,IY),(tw-14,th-10)], radius=10,
                            fill="white", outline=(205,195,178), width=1)
    draw.text((CX+28,IY+14), "Message Claude\u2026", font=_f(18), fill=(175,158,132))
    draw.rounded_rectangle([(tw-52,IY+7),(tw-20,th-18)], radius=7, fill=(30,27,23))
    draw.text((tw-42,IY+13), "\u2191", font=_f(20,True), fill="white")
    return img


def _render_slide_preview(outline_items: list[str], title: str,
                           tw: int, th: int) -> Image.Image:
    """渲染一張 Gamma 風格的簡報預覽，看起來像真的投影片"""
    img  = Image.new("RGB", (tw, th), (248, 247, 252))
    draw = ImageDraw.Draw(img)

    # ── Gamma 風格頂部 bar ──
    draw.rectangle([(0,0),(tw,48)], fill=(92,60,220))
    draw.text((14,10), "⚡  Gamma — AI 簡報預覽", font=_f(22,True), fill="white")
    # 三點
    for cx, col in [(tw-60,"#FF5F57"),(tw-40,"#FEBC2E"),(tw-20,"#28C840")]:
        draw.ellipse([(cx-6,18),(cx+6,30)], fill=col)

    # ── 縮圖列（模擬左側投影片清單）──
    THUMB_W = 110
    draw.rectangle([(0,48),(THUMB_W,th)], fill=(238,236,248))
    slide_colors = ["#5C3CDC","#4A90D9","#27AE60","#E67E22","#E74C3C"]
    for i, col in enumerate(slide_colors[:min(5,len(outline_items)+1)]):
        y0 = 58 + i*80
        draw.rectangle([(8,y0),(THUMB_W-8,y0+68)],
                        fill=col, outline="white", width=2)
        label = f"0{i+1}" if i < len(outline_items) else "封底"
        lw2 = draw.textlength(label, font=_f(16,True))
        draw.text(((THUMB_W-lw2)//2, y0+22), label, font=_f(16,True), fill="white")
        if i == 0:  # 選中高亮
            draw.rectangle([(4,y0-2),(THUMB_W-4,y0+70)],
                            outline=(92,60,220), width=3, fill=None)

    # ── 主投影片預覽（第一張：封面）──
    MX, MY = THUMB_W + 12, 58
    MW, MH = tw - MX - 8, th - MY - 8
    # 投影片背景（漸層效果用兩層）
    for i in range(MH):
        r = int(92 + (108-92)*(i/MH))
        g = int(60 + (80-60)*(i/MH))
        b = int(220 + (200-220)*(i/MH))
        draw.line([(MX, MY+i),(MX+MW, MY+i)], fill=(r,g,b))

    # 投影片內容
    CX = MX + MW//2
    # 標題
    sl_title = title[:20] if title else "AI 自動生成簡報"
    tw2 = draw.textlength(sl_title, font=_f(42,True))
    draw.text((CX-tw2//2, MY+50), sl_title, font=_f(42,True), fill="white")
    # 副標
    draw.rectangle([(MX+40, MY+110),(MX+MW-40, MY+114)], fill=(255,255,255,120))
    sub = "Vivi AI研習社  |  AI 職場實戰系列"
    sw = draw.textlength(sub, font=_f(22))
    draw.text((CX-sw//2, MY+122), sub, font=_f(22), fill=(220,210,255))

    # 大綱預覽（第一張之後的清單）
    draw.rectangle([(MX+30, MY+170),(MX+MW-30, MY+172)], fill=(255,255,255,80))
    y_item = MY + 188
    for i, item in enumerate(outline_items[:4]):
        num_txt = f"0{i+1}"
        draw.ellipse([(MX+40, y_item),(MX+64, y_item+24)], fill=(255,255,255,80))
        nw2 = draw.textlength(num_txt, font=_f(16,True))
        draw.text((MX+40+(24-nw2)//2, y_item+2), num_txt, font=_f(16,True), fill=(92,60,220))
        draw.text((MX+72, y_item+2), item[:24], font=_f(24), fill="white")
        y_item += 44

    # ── 底部工具列 ──
    draw.rectangle([(0, th-38),(tw, th)], fill=(228,225,245))
    tools = ["🖼️ 主題", "✏️ 編輯", "📊 圖表", "🤖 AI 生成", "▶ 簡報模式"]
    tx = 14
    for tool_name in tools:
        tw3 = draw.textlength(tool_name, font=_f(18))
        draw.text((tx, th-28), tool_name, font=_f(18), fill=(60,40,160))
        tx += tw3 + 28

    return img

# ══════════════════════════════════════════════════════
# Hook clip（真實照片版）
# ══════════════════════════════════════════════════════
def _hook_clip(pain_pts, win_pts, title, pain_audio, win_audio):
    pd = _audio_dur(pain_audio); wd = _audio_dur(win_audio)

    # ── 下載封面照片 ──
    pain_photo = _fetch_photo(
        "stressed,office,email,computer,busy,work",
        RW, AH, "cover_pain.jpg")
    win_photo = _fetch_photo(
        "success,presentation,team,laptop,smile,office",
        RW, AH, "cover_win.jpg")

    # ── Pain 幀 ──
    pi = Image.new("RGB", (W,H), (255,244,242))
    pd2 = ImageDraw.Draw(pi)
    _top(pd2, title); _bot(pd2)

    # 左側半透明背景
    left_img = Image.new("RGB", (LW+18, AH), (255,232,228))
    pi.paste(left_img, (0, AY))
    pd2.rectangle([(0,AY),(LW+18,AB)], fill=(255,232,228))

    pd2.text((36, AY+22), "😩  工作中的你", font=_f(42,True), fill=C["pain_r"])
    pd2.rectangle([(36, AY+76),(LW-18, AY+80)], fill=C["pain_r"])
    y = AY + 96
    for pt in pain_pts[:4]:
        _safe_text(pd2, (36,y), f"✕  {pt}", font=_f(32), fill=C["pain_txt"], max_width=LW-50)
        y += 56

    # 右側：真實照片
    if pain_photo:
        ph_with_overlay = _photo_with_overlay(pain_photo, RW, AH, (120,20,10), 60)
        pi.paste(ph_with_overlay, (RX, AY))
        # 照片上加大紅X
        pd2.text((RX + RW//2 - 80, AY + AH//2 - 100),
                 "✕", font=_f(200,True), fill=(220,30,20,180))
    else:
        # fallback：信箱模擬
        pd2.rectangle([(RX,AY),(W-12,AB)], fill=(255,242,240))
        pd2.text((RX+40, AY+40), "📧  47 封未讀信件等你處理",
                 font=_f(36,True), fill=C["pain_r"])
    pd2.rectangle([(RX-2,AY-2),(W-12,AB+2)], outline=C["pain_r"], width=4)
    pain_arr = np.array(pi)

    # ── Win 幀 ──
    wi = Image.new("RGB", (W,H), (242,252,244))
    wd2 = ImageDraw.Draw(wi)
    _top(wd2, title); _bot(wd2)
    wi_left = Image.new("RGB", (LW+18, AH), (224,248,228))
    wi.paste(wi_left, (0, AY))
    wd2.rectangle([(0,AY),(LW+18,AB)], fill=(224,248,228))
    wd2.text((36, AY+22), "🚀  用 AI 之後", font=_f(42,True), fill=C["win_g"])
    wd2.rectangle([(36, AY+76),(LW-18, AY+80)], fill=C["win_g"])
    y = AY + 96
    for wt in win_pts[:4]:
        _safe_text(wd2, (36,y), f"✅  {wt}", font=_f(32), fill=C["win_txt"], max_width=LW-50)
        y += 56

    # 右側：成果照片
    if win_photo:
        ph_with_overlay = _photo_with_overlay(win_photo, RW, AH, (10,60,20), 50)
        wi.paste(ph_with_overlay, (RX, AY))
        wd2.text((RX+20, AY+16), "✅  AI 30秒搞定",
                 font=_f(44,True), fill=(255,255,255))
    else:
        wd2.rectangle([(RX,AY),(W-12,AB)], fill=(240,252,242))
        wd2.text((RX+40, AY+40), "✅  AI 整理完成",
                 font=_f(44,True), fill=C["win_g"])
    wd2.rectangle([(RX-2,AY-2),(W-12,AB+2)], outline=C["win_g"], width=4)
    win_arr = np.array(wi)

    pc = VideoClip(lambda t: pain_arr, duration=pd)
    wc = VideoClip(lambda t: win_arr,  duration=wd)
    if Path(pain_audio).exists(): pc = pc.set_audio(AudioFileClip(pain_audio))
    if Path(win_audio).exists():  wc = wc.set_audio(AudioFileClip(win_audio))
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
    if Path(type_audio).exists(): tc = tc.set_audio(AudioFileClip(type_audio))
    if Path(out_audio).exists():  oc = oc.set_audio(AudioFileClip(out_audio))
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
    if Path(cta_audio).exists(): clip = clip.set_audio(AudioFileClip(cta_audio))
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
