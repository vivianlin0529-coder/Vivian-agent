"""
台股蓄勢待噴選股系統 v6
Phase 0 前置篩選 → Phase 1 技術指標（含日/週縮軌）→ Phase 2 量能+K棒 → Stop Loss
每個交易日 13:30 自動執行，結果寄送 Email

環境變數（GitHub Secrets）：
  GMAIL_USER    : 寄件 Gmail 帳號
  GMAIL_APP_PWD : Gmail 應用程式密碼（16碼）
  MAIL_TO       : 收件人（逗號分隔）
"""

import os, time, warnings, smtplib
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import requests
import pandas as pd
import numpy as np
import yfinance as yf
import twstock

warnings.filterwarnings("ignore")

TODAY      = date.today().strftime("%Y%m%d")
TODAY_DISP = date.today().strftime("%Y/%m/%d")
NOW_DISP   = datetime.now().strftime("%Y/%m/%d %H:%M")

CFG = dict(
    vol_threshold = 1000,
    bias1_max     = 2.4,
    bias2_max     = 3.0,
    bias3_max     = 6.4,
    adx_max       = 14,
    vol_mult      = 1.5,
    bbw_pct       = 0.8,
    atr_mult      = 2.0,
    body_min      = 0.4,
    max_workers   = 4,
    trial_n       = None,
)

GMAIL_USER    = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PWD = os.environ.get("GMAIL_APP_PWD", "")
MAIL_TO       = os.environ.get("MAIL_TO", GMAIL_USER)

stats = {k: 0 for k in (
    "etf","finance","telecom","textile","vol","bias",
    "p1_ma","p1_macd","p1_adx","p1_bbw",
    "p2_vol","p2_candle","final","err"
)}

# ── 純 pandas 技術指標 ────────────────────────────────────────────────────────
def calc_atr(high, low, close, n=14):
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def calc_adx(high, low, close, n=14):
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/n, adjust=False).mean()

    up   = high - high.shift(1)
    down = low.shift(1) - low

    dm_plus  = up.where((up > down) & (up > 0), 0.0)
    dm_minus = down.where((down > up) & (down > 0), 0.0)

    di_plus  = 100 * dm_plus.ewm(alpha=1/n, adjust=False).mean()  / atr
    di_minus = 100 * dm_minus.ewm(alpha=1/n, adjust=False).mean() / atr

    dx  = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
    adx = dx.ewm(alpha=1/n, adjust=False).mean()
    return adx, di_plus, di_minus

def calc_bbands(close, length=20, std=2.0):
    mid   = close.rolling(length).mean()
    sigma = close.rolling(length).std(ddof=0)
    upper = mid + std * sigma
    lower = mid - std * sigma
    bbw   = (upper - lower) / mid * 100
    return bbw

def calc_macd(close):
    e12 = close.ewm(span=12, adjust=False).mean()
    e26 = close.ewm(span=26, adjust=False).mean()
    dif = e12 - e26
    dea = dif.ewm(span=9, adjust=False).mean()
    return float(dif.iloc[-1]), float((dif - dea).iloc[-1])

def bias(close, n):
    ma = close.rolling(n).mean()
    return abs((close.iloc[-1] - ma.iloc[-1]) / ma.iloc[-1] * 100)

def bbw_squeeze(bbw, ma_len, thr=0.8):
    if bbw is None or len(bbw) < ma_len + 5:
        return False, np.nan, np.nan
    ma  = bbw.rolling(ma_len).mean()
    cur = float(bbw.iloc[-1]); mac = float(ma.iloc[-1])
    if np.isnan(cur) or np.isnan(mac):
        return False, cur, mac
    narrow = cur < mac * thr
    shrink = len(bbw) >= 3 and bbw.iloc[-3] > bbw.iloc[-2] > bbw.iloc[-1]
    return (narrow and shrink), cur, mac

# ── 股票清單 ──────────────────────────────────────────────────────────────────
def get_stock_list():
    raw = requests.get(
        "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
        timeout=15
    ).json()
    tw_info = {k: v for k, v in twstock.codes.items()
               if len(k) == 4 and k.isdigit()}
    stock_list = []
    for d in raw:
        code = d["Code"]
        if len(code) != 4 or not code.isdigit() or code.startswith("0"):
            stats["etf"] += 1; continue
        group = tw_info[code].group if code in tw_info else ""
        name  = tw_info[code].name  if code in tw_info else d["Name"]
        if any(g in group for g in ["金融","保險"]): stats["finance"]  += 1; continue
        if "通信" in group:                            stats["telecom"]  += 1; continue
        if "紡織" in group:                            stats["textile"]  += 1; continue
        try:   vz = int(d["TradeVolume"]) // 1000
        except: vz = 0
        if vz < CFG["vol_threshold"]: stats["vol"] += 1; continue
        stock_list.append({"code": code, "name": name, "group": group, "vz": vz})
    return stock_list, len(raw)

# ── 下載 K 線 ─────────────────────────────────────────────────────────────────
def fetch_df(code):
    try:
        df = yf.download(f"{code}.TW", period="15mo",
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < 60: return None
        df.columns = [c[0].lower() for c in df.columns]
        return df
    except: return None

# ── 單股篩選 ──────────────────────────────────────────────────────────────────
def screen(s):
    code = s["code"]
    df = fetch_df(code)
    if df is None: stats["err"] += 1; return None

    c = df["close"].dropna(); h = df["high"].dropna()
    l = df["low"].dropna();   v = df["volume"].dropna(); o = df["open"].dropna()
    if len(c) < 60: return None

    # BIAS
    if len(c) < 24: return None
    b1, b2, b3 = bias(c,6), bias(c,12), bias(c,24)
    if not (b1<CFG["bias1_max"] and b2<CFG["bias2_max"] and b3<CFG["bias3_max"]):
        stats["bias"] += 1; return None

    # A. 均線聚攏
    if len(c) < 240: stats["p1_ma"] += 1; return None
    m20  = float(c.rolling(20).mean().iloc[-1])
    m60  = float(c.rolling(60).mean().iloc[-1])
    m120 = float(c.rolling(120).mean().iloc[-1])
    m240 = float(c.rolling(240).mean().iloc[-1])
    cl   = float(c.iloc[-1])
    sp   = (max(m20,m60,m120,m240) - min(m20,m60,m120,m240)) / m20 * 100
    bma  = abs(cl - m20) / m20 * 100
    if not (sp < 5.0 and bma < 3.0): stats["p1_ma"] += 1; return None

    # B. MACD
    dif, hist = calc_macd(c)
    if not (hist < 0.05 and dif < 0.3): stats["p1_macd"] += 1; return None

    # C. ADX
    adx_s, dp_s, dm_s = calc_adx(h, l, c)
    av = float(adx_s.iloc[-1]); dp = float(dp_s.iloc[-1]); dm = float(dm_s.iloc[-1])
    if np.isnan(av) or not (av < CFG["adx_max"] and dp < 20 and dm < 20):
        stats["p1_adx"] += 1; return None

    # H1. 日線縮軌
    bw_d = calc_bbands(c, 20, 2)
    h1, d_cur, d_ma = bbw_squeeze(bw_d, 20, CFG["bbw_pct"])

    # H2. 週線縮軌
    df_w = df.resample("W-FRI").agg({
        "open":"first","high":"max","low":"min","close":"last","volume":"sum"
    }).dropna()
    bw_w = calc_bbands(df_w["close"], 20, 2)
    h2, w_cur, w_ma = bbw_squeeze(bw_w, 10, CFG["bbw_pct"])

    if not (h1 and h2): stats["p1_bbw"] += 1; return None

    # F. 量能
    v5  = float(v.shift(1).rolling(5).mean().iloc[-1])
    v20 = float(v.shift(1).rolling(20).mean().iloc[-1])
    vc  = float(v.iloc[-1])
    f1  = vc > v5  * CFG["vol_mult"]
    f2  = vc > v20 * CFG["vol_mult"]
    f3  = len(v) >= 3 and v.iloc[-3] < v.iloc[-2] < v.iloc[-1]
    if not (f1 and (f2 or f3)): stats["p2_vol"] += 1; return None

    # G. K棒
    ov = float(o.iloc[-1]); hv = float(h.iloc[-1]); lv = float(l.iloc[-1])
    bd  = abs(cl - ov); rng = hv - lv + 1e-9; ush = hv - max(cl, ov)
    g1 = cl > m20; g2 = cl > ov
    g3 = (bd/rng) > CFG["body_min"]
    g4 = (ush/rng) < 0.3
    g5 = len(c) >= 3 and cl > float(c.iloc[-2])
    if not (g1 and g2 and g3 and g4 and g5): stats["p2_candle"] += 1; return None

    # Stop Loss
    atr_s = calc_atr(h, l, c)
    at    = float(atr_s.iloc[-1])
    sl_a  = round(cl - at * CFG["atr_mult"], 2)
    sl_l  = round(float(l.iloc[-5:].min()) * 0.99, 2)
    sl_m  = round(m20 * 0.98, 2)
    slf   = max(sl_a, sl_l, sl_m)
    rsk   = round((cl - slf) / cl * 100, 2)
    rr    = round(10.0 / rsk, 2) if rsk > 0 else 0

    stats["final"] += 1
    return {
        "代號": code, "名稱": s["name"], "產業": s["group"],
        "收盤": round(cl, 2),
        "BIAS1%": round(b1,2), "BIAS2%": round(b2,2), "BIAS3%": round(b3,2),
        "MA_spread%": round(sp,2), "MA20乖離%": round(bma,2),
        "MACD_hist": round(hist,4), "ADX": round(av,1),
        "D+": round(dp,1), "D-": round(dm,1),
        "BBW日%": round(d_cur,2) if not np.isnan(d_cur) else "N/A",
        "BBW週%": round(w_cur,2) if not np.isnan(w_cur) else "N/A",
        "量/5日均": round(vc/(v5+1),2),
        "量/20日均": round(vc/(v20+1),2),
        "sl_atr": sl_a, "sl_low": sl_l, "sl_ma": sl_m,
        "sl_final": slf, "risk%": rsk, "R:R": rr,
    }

# ── Email ─────────────────────────────────────────────────────────────────────
def build_html(results, stats_snap, total_raw, phase0_n, elapsed):
    has = len(results) > 0
    funnel = [
        ("TWSE 原始股票",       total_raw,              "#37474F"),
        ("排除 ETF",            stats_snap["etf"],      "#9E9E9E"),
        ("排除金融保險",         stats_snap["finance"],  "#9E9E9E"),
        ("排除電信",            stats_snap["telecom"],  "#9E9E9E"),
        ("排除紡織",            stats_snap["textile"],  "#9E9E9E"),
        ("排除低量<1000張",      stats_snap["vol"],      "#9E9E9E"),
        ("Phase 0 通過 ✅",     phase0_n,               "#2E7D32"),
        ("排除 BIAS 不符",       stats_snap["bias"],     "#E65100"),
        ("排除均線未聚攏(A)",    stats_snap["p1_ma"],    "#E65100"),
        ("排除 MACD 未趨0(B)",   stats_snap["p1_macd"],  "#E65100"),
        ("排除 ADX 過高(C)",     stats_snap["p1_adx"],   "#E65100"),
        ("排除縮軌不符(H1+H2)", stats_snap["p1_bbw"],   "#E65100"),
        ("排除量能不足(F)",      stats_snap["p2_vol"],   "#E65100"),
        ("排除K棒不符(G)",       stats_snap["p2_candle"],"#E65100"),
        ("★ 最終候選股",        stats_snap["final"],    "#1565C0"),
    ]
    rows_f = "".join(
        f'<tr><td style="padding:4px 14px;color:{c}">{lb}</td>'
        f'<td style="padding:4px 14px;text-align:right;font-weight:bold;color:{c}">{n}</td></tr>'
        for lb,n,c in funnel
    )
    if has:
        cols = ["代號","名稱","產業","收盤","BBW日%","BBW週%","量/5日均","sl_final","risk%","R:R"]
        th = "".join(f'<th style="background:#1A237E;color:white;padding:8px 10px">{c}</th>' for c in cols)
        trs = ""
        for i,r in enumerate(results):
            bg = "#EEF2FF" if i%2==0 else "#FFFFFF"
            rrc = "#1B5E20" if float(r["R:R"])>=2.0 else "#C62828"
            trs += f'<tr style="background:{bg}">'
            for col in cols:
                v = r.get(col,"")
                sc = f'color:{rrc};font-weight:bold' if col=="R:R" else ("color:#1A237E;font-weight:bold" if col=="代號" else "")
                trs += f'<td style="padding:7px 10px;text-align:center;{sc}">{v}</td>'
            trs += "</tr>"
        result_html = f"""<h3 style="color:#1A237E;margin-top:24px">📋 候選股（依 R:R 排序）</h3>
        <table style="border-collapse:collapse;width:100%;font-size:13px"><tr>{th}</tr>{trs}</table>
        <p style="font-size:11px;color:#888;margin-top:8px">R:R ≥ 2.0 才建議進場。本報告僅供參考，投資風險自負。</p>"""
    else:
        result_html = '<div style="background:#FFF3E0;border-left:4px solid #FF9800;padding:16px;border-radius:4px;margin-top:16px"><strong>今日無符合條件候選股</strong><br>條件嚴格，耐心等待。</div>'

    return f"""<html><body style="font-family:Arial,sans-serif;max-width:720px;margin:0 auto;padding:20px">
      <div style="background:#1A237E;border-radius:8px;padding:20px;margin-bottom:20px;color:white">
        <h2 style="margin:0">🎯 台股蓄勢待噴選股報告</h2>
        <p style="margin:6px 0 0;opacity:.85">{TODAY_DISP} 收盤後 ｜ {NOW_DISP} ｜ 耗時 {elapsed:.0f}s</p>
      </div>
      <div style="background:{'#E8F5E9' if has else '#FFF3E0'};border-left:4px solid {'#2E7D32' if has else '#FF9800'};padding:14px;border-radius:4px;margin-bottom:20px">
        <strong style="font-size:16px;color:{'#2E7D32' if has else '#E65100'}">★ 今日候選股：{stats_snap['final']} 支</strong>
      </div>
      <h3 style="color:#37474F">📊 篩選統計</h3>
      <table style="border-collapse:collapse;font-size:13px;min-width:320px">{rows_f}</table>
      {result_html}
      <hr style="margin-top:32px;border:none;border-top:1px solid #eee">
      <p style="font-size:11px;color:#aaa">台股蓄勢待噴選股系統 v6 ｜ 每日 13:30 自動發送</p>
    </body></html>"""

def send_email(subject, html_body, csv_path=None):
    if not GMAIL_USER or not GMAIL_APP_PWD:
        print("  ⚠️  未設定 GMAIL_USER / GMAIL_APP_PWD，跳過寄信"); return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = MAIL_TO
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    if csv_path and os.path.exists(csv_path):
        with open(csv_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(csv_path)}"')
        msg.attach(part)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(GMAIL_USER, GMAIL_APP_PWD)
            srv.sendmail(GMAIL_USER, [r.strip() for r in MAIL_TO.split(",")], msg.as_bytes())
        print(f"  ✅ Email 發送：{MAIL_TO}")
    except Exception as e:
        print(f"  ❌ Email 失敗：{e}")

# ── 主流程 ────────────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    print("="*60)
    print(f"  台股蓄勢待噴選股系統 v6  |  {NOW_DISP}")
    print("="*60)

    print("\n[1] 取得 TWSE 清單...")
    stock_list, total_raw = get_stock_list()
    phase0_n = len(stock_list)
    print(f"    Phase 0 通過：{phase0_n} 支")

    sample = stock_list if not CFG["trial_n"] else stock_list[:CFG["trial_n"]]
    n = len(sample)
    print(f"\n[2] 技術篩選（{'全市場' if not CFG['trial_n'] else f'試跑前{n}支'}）...")

    results = []; done = 0
    with ThreadPoolExecutor(max_workers=CFG["max_workers"]) as ex:
        futs = {ex.submit(screen, s): s for s in sample}
        for fut in as_completed(futs):
            done += 1
            r = fut.result()
            if r: results.append(r)
            if done % 50 == 0:
                print(f"    {done}/{n}  候選 {len(results)} 支")
            time.sleep(0.1)

    df_out = pd.DataFrame(results).sort_values("R:R", ascending=False) if results else pd.DataFrame()
    csv_path = f"/tmp/台股選股_{TODAY}.csv"
    if not df_out.empty:
        df_out.to_csv(csv_path, index=False, encoding="utf-8-sig")

    elapsed = time.time() - t0

    print(f"\n{'='*60}\n  掃描報告\n{'='*60}")
    print(f"  TWSE 原始           : {total_raw}")
    print(f"  [P0] ETF            : -{stats['etf']}")
    print(f"  [P0] 金融保險       : -{stats['finance']}")
    print(f"  [P0] 電信           : -{stats['telecom']}")
    print(f"  [P0] 紡織           : -{stats['textile']}")
    print(f"  [P0] 低量           : -{stats['vol']}")
    print(f"  [P0] 通過           :  {phase0_n}")
    print(f"  [P0] BIAS不符       : -{stats['bias']}")
    print(f"  [P1-A] 均線未聚攏  : -{stats['p1_ma']}")
    print(f"  [P1-B] MACD未趨0   : -{stats['p1_macd']}")
    print(f"  [P1-C] ADX過高     : -{stats['p1_adx']}")
    print(f"  [P1-H] 縮軌不符   : -{stats['p1_bbw']}")
    print(f"  [P2-F] 量能不足   : -{stats['p2_vol']}")
    print(f"  [P2-G] K棒不符    : -{stats['p2_candle']}")
    print(f"  ★ 最終候選股      :  {stats['final']}")
    print(f"  ⏱  耗時            :  {elapsed:.0f}s")
    print(f"{'='*60}")

    if results:
        print(f"\n  {'代號':<6}{'名稱':<10}{'產業':<12}{'收盤':<8}{'停損':<8}{'risk%':<8}{'R:R'}")
        print("  "+"-"*56)
        for r in df_out.to_dict("records"):
            print(f"  {r['代號']:<6}{r['名稱']:<10}{r['產業'][:10]:<12}"
                  f"{r['收盤']:<8}{r['sl_final']:<8}{r['risk%']:<8}{r['R:R']}")

    print("\n[3] 發送 Email...")
    has = stats["final"] > 0
    subj = f"【台股選股】{TODAY_DISP} 候選股 {stats['final']} 支 🎯" if has else f"【台股選股】{TODAY_DISP} 今日無候選股"
    html = build_html(results=df_out.to_dict("records") if not df_out.empty else [],
                      stats_snap=dict(stats), total_raw=total_raw,
                      phase0_n=phase0_n, elapsed=elapsed)
    send_email(subj, html, csv_path if not df_out.empty else None)
    print("\n✅ 完成")

if __name__ == "__main__":
    trial = os.environ.get("TRIAL_N","")
    CFG["trial_n"] = int(trial) if trial.strip().isdigit() else None
    main()
