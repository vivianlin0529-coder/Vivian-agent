"""
video_renderer.py — Vivi AI研習社
每段視覺 = 自己的 TTS 音頻 → 保證完美口說同步
總長 ~50-58 秒
"""
from __future__ import annotations
import textwrap, numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import AudioFileClip, VideoClip, concatenate_videoclips

W,H   = 1920,1080
FPS   = 15
TOP_H = 64; BOT_H = 60
AY = TOP_H+4; AB = H-BOT_H-4; AH = AB-AY
LW = 680; RX = 726; RW = W-RX-14
BRAND = "Vivi AI研習社"

C = dict(
    bg=(242,239,234),brand_bg=(34,24,12),gold=(206,158,68),
    sep=(160,84,38),accent=(160,84,38),acdk=(108,50,14),
    hd=(24,16,6),bd=(68,48,28),lbg=(228,220,206),
    bot_bg=(34,24,12),bot_fg=(188,160,108),
    cbg=(252,250,246),tbar=(40,30,18),
    pbg=(226,244,222),pfg=(16,70,16),
    obg=(246,240,228),ofg=(32,22,8),
    lbl=(160,84,38),lblf=(255,255,255),
    think=(118,96,64),acdk2=(108,50,14),
    pain_bg=(255,246,243),pain_r=(195,35,18),pain_txt=(88,28,12),
    win_bg=(241,250,241),win_g=(18,132,38),win_txt=(12,64,18),
)

_FC: dict = {}
def _f(sz,bold=False):
    k=(sz,bold)
    if k not in _FC:
        pb=["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc","C:/Windows/Fonts/msjhbd.ttc"]
        pr=["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc","C:/Windows/Fonts/msjh.ttc"]
        for p in (pb if bold else pr):
            if Path(p).exists():
                try: _FC[k]=ImageFont.truetype(p,sz); break
                except: pass
        if k not in _FC: _FC[k]=ImageFont.load_default()
    return _FC[k]

def _top(draw,title=""):
    draw.rectangle([(0,0),(W,TOP_H)],fill=C["brand_bg"])
    draw.text((30,(TOP_H-30)//2),BRAND,font=_f(30,True),fill=C["gold"])
    if title:
        tw=draw.textlength(title[:50],font=_f(24))
        draw.text(((W-tw)//2,(TOP_H-24)//2),title[:50],font=_f(24),fill=(155,133,92))

def _bot(draw,hint="",num=0,total=0):
    draw.rectangle([(0,H-BOT_H),(W,H)],fill=C["bot_bg"])
    if hint:
        hw=draw.textlength(hint[:72],font=_f(23))
        draw.text(((W-hw)//2,H-BOT_H+(BOT_H-23)//2),hint[:72],font=_f(23),fill=C["bot_fg"])
    if total:
        r,g=6,16; sx=W-(total*(r*2+g))-22; sy=H-12
        for i in range(1,total+1):
            draw.ellipse([(sx,sy-r),(sx+r*2,sy+r)],
                         fill=C["gold"] if i==num else (66,52,30)); sx+=r*2+g

def _audio_dur(path):
    try: return AudioFileClip(path).duration
    except: return 7.0

# ── 信箱爆滿 mockup ─────────────────────────────────
def _inbox() -> Image.Image:
    img=Image.new("RGB",(RW,AH),(245,245,245))
    d=ImageDraw.Draw(img)
    d.rectangle([(0,0),(RW,44)],fill=(0,72,177))
    d.text((14,10),"📧  收件匣（47 封未讀）",font=_f(22,True),fill="white")
    d.rectangle([(8,52),(RW-8,80)],fill="white",outline="#CCC",width=1)
    d.text((16,58),"搜尋信件…",font=_f(20),fill="#AAAAAA")
    rows=[
        ("[急！] 請問上週報告什麼時候可以給我？","今天 09:14",True),
        ("RE:RE:RE: 合約條款第三點修改意見…","今天 08:52",True),
        ("【提醒】週五前請填寫差旅費報銷單","昨天 17:33",True),
        ("Fwd: 下週一會議議程（各單位確認）","昨天 14:11",False),
        ("RE: 關於新客戶提案，我有幾點想法…","昨天 11:08",True),
        ("客戶反映產品問題，請盡速回覆","週二 10:22",True),
        ("[會議記錄] 月會紀錄（共12頁請存檔）","週二 09:00",False),
        ("[提醒×3] 績效面談表格尚未填寫","上週五",True),
    ]
    y=92
    for subj,time,unread in rows:
        bg=(255,242,242) if unread else (255,255,255)
        d.rectangle([(0,y),(RW,y+52)],fill=bg,outline="#EEE",width=1)
        dot=(195,35,18) if unread else (180,180,180)
        d.ellipse([(10,y+19),(20,y+29)],fill=dot)
        d.text((28,y+7),subj[:38],font=_f(20,bold=unread),fill="#222")
        d.text((28,y+31),time,font=_f(17),fill="#888")
        y+=54
        if y>AH-36: break
    d.rectangle([(0,AH-34),(RW,AH)],fill="#F0F0F0")
    d.text((14,AH-26),"草稿：Email_回覆_v8_FINAL_FINAL.docx  ❌ 還沒寄出",font=_f(17),fill="#CC3333")
    return img

# ── AI整理好輸出 mockup ──────────────────────────────
def _ai_output_mock() -> Image.Image:
    img=Image.new("RGB",(RW,AH),(250,252,248))
    d=ImageDraw.Draw(img)
    d.rectangle([(0,0),(RW,44)],fill=(18,132,58))
    d.text((14,10),"✅  Claude 整理結果（剛剛生成）",font=_f(22,True),fill="white")
    y=58
    d.text((18,y),"【本週重點摘要 × 待辦清單】",font=_f(26,True),fill=(12,80,24)); y+=42
    d.rectangle([(12,y),(RW-12,y+2)],fill="#A8D8A8"); y+=12
    items=[
        ("📧","今日回覆","客戶問題 → Email 草稿已生成，待確認後寄出"),
        ("📋","週五截止","差旅費報銷 → 表格已填，金額 NT$4,280"),
        ("📊","週一前","KPI 追蹤表 → Q1 完成率 87%，缺口已標紅"),
        ("🗂️","存檔完成","月會紀錄 → 5行重點版＋完整版已整理"),
    ]
    for icon,when,desc in items:
        d.rectangle([(12,y),(RW-12,y+60)],fill="white",outline="#C8E8C8",width=1)
        d.text((20,y+8),f"{icon}  {when}",font=_f(19,True),fill=(12,80,24))
        d.text((20,y+32),f"   {desc}",font=_f(19),fill="#333"); y+=66
    d.rectangle([(12,y+8),(RW-12,y+10)],fill="#C8E8C8")
    d.text((18,y+18),"💡 以上由 AI 生成，點擊任一項可展開完整內容",font=_f(17),fill="#166534")
    return img

# ── Hook clip（pain + win，各自音頻）───────────────────
def _hook_clip(pain_pts,win_pts,title,pain_audio,win_audio):
    pd=_audio_dur(pain_audio); wd=_audio_dur(win_audio)

    # Pain frame
    pi=Image.new("RGB",(W,H),C["pain_bg"]); pdr=ImageDraw.Draw(pi)
    _top(pdr,title); _bot(pdr)
    pdr.rectangle([(0,AY),(LW+18,AB)],fill=C["lbg"])
    pdr.text((36,AY+22),"😩  現在的你",font=_f(42,True),fill=C["pain_r"])
    pdr.rectangle([(36,AY+76),(LW-18,AY+80)],fill=C["pain_r"])
    y=AY+96
    for pt in pain_pts[:4]: pdr.text((36,y),f"✕  {pt[:24]}",font=_f(32),fill=C["pain_txt"]); y+=56
    pi.paste(_inbox(),(RX,AY))
    pdr.rectangle([(RX-2,AY-2),(W-12,AB+2)],outline=C["pain_r"],width=3)
    pain_arr=np.array(pi)

    # Win frame
    wi=Image.new("RGB",(W,H),C["win_bg"]); wdr=ImageDraw.Draw(wi)
    _top(wdr,title); _bot(wdr)
    wdr.rectangle([(0,AY),(LW+18,AB)],fill=C["lbg"])
    wdr.text((36,AY+22),"🚀  用 AI 之後",font=_f(42,True),fill=C["win_g"])
    wdr.rectangle([(36,AY+76),(LW-18,AY+80)],fill=C["win_g"])
    y=AY+96
    for wt in win_pts[:4]: wdr.text((36,y),f"✅  {wt[:24]}",font=_f(32),fill=C["win_txt"]); y+=56
    wi.paste(_ai_output_mock(),(RX,AY))
    wdr.rectangle([(RX-2,AY-2),(W-12,AB+2)],outline=C["win_g"],width=3)
    win_arr=np.array(wi)

    pc=VideoClip(lambda t:pain_arr,duration=pd)
    wc=VideoClip(lambda t:win_arr,duration=wd)
    if Path(pain_audio).exists(): pc=pc.set_audio(AudioFileClip(pain_audio))
    if Path(win_audio).exists():  wc=wc.set_audio(AudioFileClip(win_audio))
    return concatenate_videoclips([pc,wc],method="compose")

# ── Step clip（typing 音頻 + output 音頻）────────────────
def _step_clip(step,title,total,type_audio,out_audio):
    td=_audio_dur(type_audio); od=_audio_dur(out_audio)
    num=step.get("num",1); head=step.get("heading","")
    bulls=step.get("bullets") or []; action=step.get("action_label","")
    tool=step.get("tool_name","Claude"); prompt=step.get("example_prompt","").strip()
    output=step.get("example_output") or []; tip=step.get("tip","")
    out_text="\n".join(output)

    # 靜態左側
    base=Image.new("RGB",(W,H),C["bg"]); bd2=ImageDraw.Draw(base)
    _top(bd2,title); _bot(bd2,action,num,total)
    bd2.rectangle([(0,AY),(LW+18,AB)],fill=C["lbg"])
    bd2.rectangle([(LW+16,AY),(LW+22,AB)],fill=C["sep"])
    cx,cy,r=74,AY+62,38
    bd2.ellipse([(cx-r,cy-r),(cx+r,cy+r)],fill=C["accent"])
    nw=bd2.textlength(str(num),font=_f(40,True)); bd2.text((cx-nw//2,cy-24),str(num),font=_f(40,True),fill=(255,255,255))
    fh=_f(50,True); hw=bd2.textlength(head,font=fh); fh=_f(40,True) if hw>LW-36 else fh
    bd2.text((30,AY+112),head,font=fh,fill=C["hd"])
    bd2.rectangle([(30,AY+184),(LW-8,AY+188)],fill=C["sep"])
    y=AY+204
    for i,b in enumerate(bulls[:3]):
        tw2=bd2.textlength(f"0{i+1}",font=_f(15,True))
        bd2.rectangle([(30,y+2),(30+32,y+32)],fill=C["accent"])
        bd2.text((30+(32-tw2)//2,y+7),f"0{i+1}",font=_f(15,True),fill=(255,255,255))
        bd2.text((70,y+4),b[:18],font=_f(28),fill=C["bd"]); y+=54
    if tip and y<AB-60:
        bd2.rectangle([(22,y+8),(LW-4,y+52)],fill=C["acdk"])
        bd2.text((36,y+16),f"💡 {tip[:26]}",font=_f(22),fill=(255,215,135))
    base_arr=np.array(base)

    # 右側動態
    PAD=14; BAR=44; LBL=26
    pwl=[]
    for seg in prompt.split("\n"): pwl+=(textwrap.wrap(seg,width=33) or [""])
    PH=max(len(pwl)*29+16,68)
    OUT_Y=AY+BAR+PAD+LBL+6+PH+PAD+LBL+6

    def _R(arr,sp,so,dots):
        img2=Image.fromarray(arr.copy()); d2=ImageDraw.Draw(img2)
        rx=RX
        d2.rectangle([(rx,AY),(W-12,AB)],fill=C["cbg"])
        d2.rectangle([(rx,AY),(W-12,AY+BAR)],fill=C["tbar"])
        for cx2,col in [(rx+13,"#FF5F57"),(rx+29,"#FEBC2E"),(rx+45,"#28C840")]:
            d2.ellipse([(cx2-5,AY+16),(cx2+5,AY+26)],fill=col)
        d2.text((rx+60,AY+10),tool,font=_f(22,True),fill=(210,180,128))
        y2=AY+BAR+PAD
        d2.rectangle([(rx+PAD,y2),(W-22,y2+LBL)],fill=C["lbl"])
        d2.text((rx+PAD+7,y2+4),"✏️  你輸入的指令",font=_f(15),fill=C["lblf"])
        y2+=LBL+6
        d2.rectangle([(rx+PAD,y2),(W-22,y2+PH)],fill=C["pbg"],outline="#9ED09E",width=2)
        py2=y2+8
        for line in sp.split("\n"):
            for wl in (textwrap.wrap(line,width=32) or [line]):
                d2.text((rx+PAD+8,py2),wl,font=_f(20),fill=C["pfg"]); py2+=29
        y2+=PH+PAD
        d2.rectangle([(rx+PAD,y2),(W-22,y2+LBL)],fill=C["lbl"])
        d2.text((rx+PAD+7,y2+4),"🤖  AI 輸出結果",font=_f(15),fill=C["lblf"])
        y2+=LBL+6
        ob_h=AB-y2-PAD
        d2.rectangle([(rx+PAD,y2),(W-22,AB-PAD)],fill=C["obg"],outline="#C8B870",width=2)
        if dots>=0:
            dc="●"*dots+"○"*(3-dots)
            d2.text((rx+PAD+10,y2+10),f"AI 生成中  {dc}",font=_f(24),fill=C["think"])
        else:
            oy=y2+8
            for line in so.split("\n"):
                if oy+28>AB-PAD-6: break
                col=C["acdk2"] if line.startswith(("•","【","✅","⚠️","→","—","📌","💡")) else C["ofg"]
                d2.text((rx+PAD+10,oy),line[:38],font=_f(20),fill=col); oy+=28
        d2.rectangle([(rx-2,AY-2),(W-10,AB+2)],outline=C["sep"],width=3)
        return np.array(img2)

    def tf(t):
        p=t/td; n=int(p*len(prompt))
        cur="▋" if int(t/0.5)%2==0 else ""
        return _R(base_arr,prompt[:n]+cur,"",-2)

    T_THINK=0.20
    def of(t):
        p=t/od
        if p<T_THINK: return _R(base_arr,prompt,"",int((p/T_THINK)*4)%4)
        op=(p-T_THINK)/(1-T_THINK); n=int(op*len(out_text))
        return _R(base_arr,prompt,out_text[:n],-1)

    tc=VideoClip(tf,duration=td); oc=VideoClip(of,duration=od)
    if Path(type_audio).exists(): tc=tc.set_audio(AudioFileClip(type_audio))
    if Path(out_audio).exists():  oc=oc.set_audio(AudioFileClip(out_audio))
    return concatenate_videoclips([tc,oc],method="compose")

# ── CTA ──────────────────────────────────────────────
def _cta_clip(title,cta_audio):
    dur=_audio_dur(cta_audio)
    img=Image.new("RGB",(W,H),C["bg"]); d=ImageDraw.Draw(img)
    _top(d,title); _bot(d)
    d.rectangle([(110,H//2-3),(W-110,H//2+1)],fill=C["sep"])
    for txt,sz,bold,yo in [
        ("🔔  訂閱 Vivi AI研習社，每週更新職場 AI 實戰",50,True,-68),
        ("👇  留言你想學的工具，我下週教你",40,False,28),
    ]:
        tw=d.textlength(txt,font=_f(sz,bold))
        d.text(((W-tw)//2,H//2+yo),txt,font=_f(sz,bold),fill=C["hd"] if bold else C["bd"])
    arr=np.array(img)
    clip=VideoClip(lambda t:arr,duration=dur)
    if Path(cta_audio).exists(): clip=clip.set_audio(AudioFileClip(cta_audio))
    return clip

# ── 主入口 ────────────────────────────────────────────
def render_tutorial_video(segments:dict, steps:list,
                          title:str="", output:str="video_final.mp4") -> str:
    print(f"  🎬 渲染：{title}")
    pain_pts=steps[0].get("pain_points",[]) if steps else []
    win_pts =steps[0].get("win_points",[])  if steps else []

    clips=[]
    clips.append(_hook_clip(pain_pts,win_pts,title,
                            segments.get("pain",""),segments.get("win","")))
    print("  ✅ Hook")
    for i,step in enumerate(steps,1):
        clips.append(_step_clip(step,title,len(steps),
                                segments.get(f"step{i}_type",""),
                                segments.get(f"step{i}_out","")))
        print(f"  ✅ Step {i}")
    clips.append(_cta_clip(title,segments.get("cta","")))
    print("  ✅ CTA")

    final=concatenate_videoclips(clips,method="compose")
    final.write_videofile(output,fps=FPS,codec="libx264",
                          audio_codec="aac",preset="fast",logger=None)
    dur=sum(c.duration for c in clips)
    size=Path(output).stat().st_size//(1024*1024)
    print(f"  ✅ {output} | {dur:.0f}s | {size} MB")
    return output
