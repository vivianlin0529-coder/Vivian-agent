"""
台股蓄勢待噴選股系統 v6
策略：Phase 0 前置篩選 → Phase 1 技術指標（含日/週縮軌）→ Phase 2 量能+K棒 → Stop Loss
排程：每個交易日 13:30 執行，完成後自動寄送 Email 報告

環境變數（GitHub Actions Secrets）：
  GMAIL_USER    : 寄件 Gmail 帳號（xxx@gmail.com）
  GMAIL_APP_PWD : Gmail 應用程式密碼（16碼）
  MAIL_TO       : 收件人（可多個，逗號分隔）
  FINMIND_TOKEN : FinMind API Token（選用，籌碼面用）
"""

import os, time, warnings, smtplib, traceback
from datetime import date, datetime, timedelta
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

# ══════════════════════════════════════════════════════════════════════════════
# 設定
# ══════════════════════════════════════════════════════════════════════════════
TODAY      = date.today().strftime("%Y%m%d")
TODAY_DISP = date.today().strftime("%Y/%m/%d")
NOW_DISP   = datetime.now().strftime("%Y/%m/%d %H:%M")

CFG = dict(
    vol_threshold = 1000,   # 流動性門檻（張）
    bias1_max     = 2.4,    # MA6  乖離%
    bias2_max     = 3.0,    # MA12 乖離%
    bias3_max     = 6.4,    # MA24 乖離%
    adx_max       = 14,     # ADX 上限
    vol_mult      = 1.5,    # 放量倍數
    bbw_pct       = 0.8,    # 縮軌門檻
    atr_mult      = 2.0,    # ATR 停損倍數
    body_min      = 0.4,    # K棒實體比
    max_workers   = 5,      # 執行緒數
    trial_n       = None,   # None=全掃，整數=試跑前N支
)

GMAIL_USER    = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PWD = os.environ.get("GMAIL_APP_PWD", "")
MAIL_TO       = os.environ.get("MAIL_TO", GMAIL_USER)

stats = {k: 0 for k in (
    "etf","finance","telecom","textile","vol","bias",
    "p1_ma","p1_macd","p1_adx","p1_bbw",
    "p2_vol","p2_candle","final","err"
)}

# ══════════════════════════════════════════════════════════════════════════════
# 股票清單（TWSE Open API）
# ══════════════════════════════════════════════════════════════════════════════
def get_stock_list():
    raw = requests.get(
        "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
        timeout=15
    ).json()
    tw_info = {k: v for k, v in twstock.codes.items()
               if len(k) == 4 and k.isdigit()}
    stock_list, total_raw = [], len(raw)

    for d in raw:
        code = d["Code"]
        if len(code) != 4 or not code.isdigit() or code.startswith("0"):
            stats["etf"] += 1; continue
        group = tw_info[code].group if code in tw_info else ""
        name  = tw_info[code].name  if code in tw_info else d["Name"]
        if any(g in group for g in ["金融", "保險"]): stats["finance"]  += 1; continue
        if "通信" in group:                            stats["telecom"]  += 1; continue
        if "紡織" in group:                            stats["textile"]  += 1; continue
        try:   vz = int(d["TradeVolume"]) // 1000
        except: vz = 0
        if vz < CFG["vol_threshold"]: stats["vol"] += 1; continue
        stock_list.append({"code": code, "name": name, "group": group, "vz": vz})

    return stock_list, total_raw

# ══════════════════════════════════════════════════════════════════════════════
# 技術指標工具
# ══════════════════════════════════════════════════════════════════════════════
def fetch_df(code):
    try:
        df = yf.download(f"{code}.TW", period="15mo",
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < 60: return None
        df.columns = [c[0].lower() for c in df.columns]
        return df
    except: return None

def bias(c, n):
    ma = c.rolling(n).mean()
    return abs((c.iloc[-1] - ma.iloc[-1]) / ma.iloc[-1] * 100)

def macd(c):
    e12 = c.ewm(span=12, adjust=False).mean()
    e26 = c.ewm(span=26, adjust=False).mean()
    dif = e12 - e26; dea = dif.ewm(span=9, adjust=False).mean()
    return float(dif.iloc[-1]), float((dif - dea).iloc[-1])

def adx_fn(h, l, c, n=14):
    try:
        import pandas_ta as ta
        res = pd.DataFrame({"high": h, "low": l, "close": c}).ta.adx(length=n)
        if res is None or res.empty: return np.nan, np.nan, np.nan
        return (float(res[f"ADX_{n}"].iloc[-1]),
                float(res[f"DMP_{n}"].iloc[-1]),
                float(res[f"DMN_{n}"].iloc[-1]))
    except: return np.nan, np.nan, np.nan

def atr_fn(h, l, c, n=14):
    try:
        import pandas_ta as ta
        r = pd.DataFrame({"high": h, "low": l, "close": c}).ta.atr(length=n)
        return float(r.iloc[-1]) if r is not None else np.nan
    except: return np.nan

def bbw_fn(c, length=20, std=2):
    try:
        import pandas_ta as ta
        bb = pd.DataFrame({"close": c}).ta.bbands(length=length, std=std)
        if bb is None or bb.empty: return pd.Series(dtype=float)
        s = float(std)
        return (bb[f"BBU_{length}_{s}"] - bb[f"BBL_{length}_{s}"]) / bb[f"BBM_{length}_{s}"] * 100
    except: return pd.Series(dtype=float)

def squeeze(bw, ma_len, thr=0.8):
    if bw is None or len(bw) < ma_len + 5: return False, np.nan, np.nan
    ma = bw.rolling(ma_len).mean()
    cur, mac = float(bw.iloc[-1]), float(ma.iloc[-1])
    if np.isnan(cur) or np.isnan(mac): return False, cur, mac
    narrow = cur < mac * thr
    shrink = len(bw) >= 3 and bw.iloc[-3] > bw.iloc[-2] > bw.iloc[-1]
    return (narrow and shrink), cur, mac

# ══════════════════════════════════════════════════════════════════════════════
# 單股篩選
# ══════════════════════════════════════════════════════════════════════════════
def screen(s):
    code = s["code"]
    df = fetch_df(code)
    if df is None: stats["err"] += 1; return None

    c = df["close"].dropna(); h = df["high"].dropna()
    l = df["low"].dropna();   v = df["volume"].dropna(); o = df["open"].dropna()
    if len(c) < 60: return None

    # ── BIAS（三線合一）
    if len(c) < 24: return None
    b1, b2, b3 = bias(c, 6), bias(c, 12), bias(c, 24)
    if not (b1 < CFG["bias1_max"] and b2 < CFG["bias2_max"] and b3 < CFG["bias3_max"]):
        stats["bias"] += 1; return None

    # ── A. 均線聚攏（MA20/60/120/240）
    if len(c) < 240: stats["p1_ma"] += 1; return None
    m20  = float(c.rolling(20).mean().iloc[-1])
    m60  = float(c.rolling(60).mean().iloc[-1])
    m120 = float(c.rolling(120).mean().iloc[-1])
    m240 = float(c.rolling(240).mean().iloc[-1])
    cl   = float(c.iloc[-1])
    sp   = (max(m20, m60, m120, m240) - min(m20, m60, m120, m240)) / m20 * 100
    bma  = abs(cl - m20) / m20 * 100
    if not (sp < 5.0 and bma < 3.0): stats["p1_ma"] += 1; return None

    # ── B. MACD 趨近0
    dif, hist = macd(c)
    if not (hist < 0.05 and dif < 0.3): stats["p1_macd"] += 1; return None

    # ── C. ADX 整理中
    av, dp, dm = adx_fn(h, l, c)
    if np.isnan(av) or not (av < CFG["adx_max"] and dp < 20 and dm < 20):
        stats["p1_adx"] += 1; return None

    # ── H1. 日線縮軌
    bw_d = bbw_fn(c, 20, 2)
    h1, d_cur, d_ma = squeeze(bw_d, 20, CFG["bbw_pct"])

    # ── H2. 週線縮軌
    df_w = df.resample("W-FRI").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last",  "volume": "sum"
    }).dropna()
    bw_w = bbw_fn(df_w["close"], 20, 2)
    h2, w_cur, w_ma = squeeze(bw_w, 10, CFG["bbw_pct"])

    if not (h1 and h2): stats["p1_bbw"] += 1; return None

    # ── F. 量能突增（F1必要 + F2/F3任1）
    v5  = float(v.shift(1).rolling(5).mean().iloc[-1])
    v20 = float(v.shift(1).rolling(20).mean().iloc[-1])
    vc  = float(v.iloc[-1])
    f1  = vc > v5  * CFG["vol_mult"]
    f2  = vc > v20 * CFG["vol_mult"]
    f3  = len(v) >= 3 and v.iloc[-3] < v.iloc[-2] < v.iloc[-1]
    if not (f1 and (f2 or f3)): stats["p2_vol"] += 1; return None

    # ── G. K棒型態
    ov = float(o.iloc[-1]); hv = float(h.iloc[-1]); lv = float(l.iloc[-1])
    bd  = abs(cl - ov); rng = hv - lv + 1e-9; ush = hv - max(cl, ov)
    g1 = cl > m20; g2 = cl > ov
    g3 = (bd / rng) > CFG["body_min"]
    g4 = (ush / rng) < 0.3
    g5 = len(c) >= 3 and cl > float(c.iloc[-2])
    if not (g1 and g2 and g3 and g4 and g5): stats["p2_candle"] += 1; return None

    # ── Stop Loss
    at    = atr_fn(h, l, c)
    sl_a  = round(cl - at * CFG["atr_mult"], 2) if not np.isnan(at) else np.nan
    sl_l  = round(float(l.iloc[-5:].min()) * 0.99, 2)
    sl_m  = round(m20 * 0.98, 2)
    slf   = max(x for x in [sl_a, sl_l, sl_m] if not np.isnan(x))
    rsk   = round((cl - slf) / cl * 100, 2)
    rr    = round(10.0 / rsk, 2) if rsk > 0 else 0

    stats["final"] += 1
    return {
        "代號": code, "名稱": s["name"], "產業": s["group"],
        "收盤": round(cl, 2),
        "BIAS1%": round(b1, 2), "BIAS2%": round(b2, 2), "BIAS3%": round(b3, 2),
        "MA_spread%": round(sp, 2), "MA20乖離%": round(bma, 2),
        "MACD_hist": round(hist, 4), "ADX": round(av, 1),
        "D+": round(dp, 1), "D-": round(dm, 1),
        "BBW日%": round(d_cur, 2), "BBW日MA%": round(d_ma, 2),
        "BBW週%": round(w_cur, 2), "BBW週MA%": round(w_ma, 2),
        "量/5日均": round(vc / (v5 + 1), 2),
        "量/20日均": round(vc / (v20 + 1), 2),
        "F1放量": "✅" if f1 else "❌",
        "F2中期量": "✅" if f2 else "❌",
        "F3量遞增": "✅" if f3 else "❌",
        "sl_atr": sl_a, "sl_low": sl_l, "sl_ma": sl_m,
        "sl_final": slf, "risk%": rsk, "R:R": rr,
    }

# ══════════════════════════════════════════════════════════════════════════════
# Email 報告
# ══════════════════════════════════════════════════════════════════════════════
def build_html(results, stats_snap, total_raw, phase0_n, elapsed):
    """產生 HTML Email 內容"""
    PASS_COLOR = "#1B5E20"; FAIL_COLOR = "#B71C1C"
    has_result = len(results) > 0

    # 漏斗統計列
    funnel_rows = [
        ("TWSE 原始股票", total_raw, "#37474F"),
        ("排除 ETF/5碼", stats_snap["etf"], "#757575"),
        ("排除金融保險", stats_snap["finance"], "#757575"),
        ("排除電信", stats_snap["telecom"], "#757575"),
        ("排除紡織", stats_snap["textile"], "#757575"),
        ("排除低量<1000張", stats_snap["vol"], "#757575"),
        ("Phase 0 通過 ✅", phase0_n, "#1B5E20"),
        ("排除 BIAS 不符", stats_snap["bias"], "#E65100"),
        ("排除均線未聚攏(A)", stats_snap["p1_ma"], "#E65100"),
        ("排除 MACD 未趨0(B)", stats_snap["p1_macd"], "#E65100"),
        ("排除 ADX 過高(C)", stats_snap["p1_adx"], "#E65100"),
        ("排除縮軌不符(H1+H2)", stats_snap["p1_bbw"], "#E65100"),
        ("排除量能不足(F)", stats_snap["p2_vol"], "#E65100"),
        ("排除 K 棒不符(G)", stats_snap["p2_candle"], "#E65100"),
        (f"★ 最終候選股", stats_snap["final"], "#1565C0"),
    ]

    funnel_html = "".join(
        f'<tr><td style="padding:4px 12px;color:{c};font-weight:{"bold" if "通過" in label or "★" in label else "normal"}">{label}</td>'
        f'<td style="padding:4px 12px;text-align:right;font-weight:bold;color:{c}">{n}</td></tr>'
        for label, n, c in funnel_rows
    )

    # 結果表格
    if has_result:
        cols = ["代號","名稱","產業","收盤","BBW日%","BBW週%","量/5日均","sl_final","risk%","R:R"]
        header_html = "".join(
            f'<th style="background:#1A237E;color:white;padding:8px 10px;text-align:center">{c}</th>'
            for c in cols
        )
        rows_html = ""
        for i, r in enumerate(results):
            bg = "#EEF2FF" if i % 2 == 0 else "#FFFFFF"
            rr_color = "#1B5E20" if float(r["R:R"]) >= 2.0 else "#E65100"
            rows_html += f'<tr style="background:{bg}">'
            for col in cols:
                v = r.get(col, "")
                style = f'style="padding:7px 10px;text-align:center'
                if col == "R:R":
                    style += f';color:{rr_color};font-weight:bold'
                elif col == "代號":
                    style += ';font-weight:bold;color:#1A237E'
                rows_html += f'<td {style}">{v}</td>'
            rows_html += "</tr>"
        result_section = f"""
        <h3 style="color:#1A237E;margin-top:24px">📋 候選股明細（依 R:R 排序）</h3>
        <table style="border-collapse:collapse;width:100%;font-size:13px">
          <tr>{header_html}</tr>
          {rows_html}
        </table>
        <p style="font-size:11px;color:#888;margin-top:8px">
          ⚠️ R:R = (目標+10%) ÷ 停損幅度，建議 R:R ≥ 2.0 才進場。此報告僅供參考，投資風險自負。
        </p>"""
    else:
        result_section = """
        <div style="background:#FFF3E0;border-left:4px solid #FF9800;padding:16px;border-radius:4px;margin-top:16px">
          <strong>今日無候選股符合所有條件</strong><br>
          條件嚴格（均線+MACD+ADX+日週縮軌+量能+K棒），建議耐心等待。
        </div>"""

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:720px;margin:0 auto;padding:20px">
      <div style="background:linear-gradient(135deg,#1A237E,#283593);
                  border-radius:8px;padding:20px;margin-bottom:20px;color:white">
        <h2 style="margin:0">🎯 台股蓄勢待噴選股報告</h2>
        <p style="margin:6px 0 0;opacity:0.85">
          {TODAY_DISP} 收盤後掃描 ｜ 執行時間：{NOW_DISP} ｜ 耗時 {elapsed:.0f} 秒
        </p>
      </div>

      <div style="background:{"#E8F5E9" if has_result else "#FFF3E0"};
                  border-left:4px solid {"#1B5E20" if has_result else "#FF9800"};
                  padding:14px;border-radius:4px;margin-bottom:20px">
        <strong style="font-size:16px;color:{"#1B5E20" if has_result else "#E65100"}">
          ★ 今日候選股：{stats_snap["final"]} 支
        </strong>
      </div>

      <h3 style="color:#37474F">📊 篩選漏斗統計</h3>
      <table style="border-collapse:collapse;width:360px;font-size:13px">
        {funnel_html}
      </table>

      {result_section}

      <hr style="margin-top:32px;border:none;border-top:1px solid #eee">
      <p style="font-size:11px;color:#aaa">
        台股蓄勢待噴選股系統 v6 ｜ Phase 0→1→2 七重條件 ｜ 日線+週線縮軌確認<br>
        本報告由 GitHub Actions 自動產生，每個交易日 13:30 發送
      </p>
    </body></html>"""
    return html


def send_email(subject, html_body, csv_path=None):
    """透過 Gmail SMTP 發送 HTML 報告"""
    if not GMAIL_USER or not GMAIL_APP_PWD:
        print("  ⚠️  未設定 GMAIL_USER / GMAIL_APP_PWD，跳過寄信")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = MAIL_TO

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # 附加 CSV
    if csv_path and os.path.exists(csv_path):
        with open(csv_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition",
                        f'attachment; filename="{os.path.basename(csv_path)}"')
        msg.attach(part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PWD)
            recipients = [r.strip() for r in MAIL_TO.split(",")]
            server.sendmail(GMAIL_USER, recipients, msg.as_bytes())
        print(f"  ✅ Email 已發送至：{MAIL_TO}")
        return True
    except Exception as e:
        print(f"  ❌ Email 發送失敗：{e}")
        return False

# ══════════════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════════════
def main():
    t_start = time.time()
    print("=" * 62)
    print("  台股蓄勢待噴選股系統 v6")
    print(f"  {NOW_DISP}  |  日線+週線縮軌 + K棒 + 量能")
    print("=" * 62)

    # Step 1: 股票清單
    print("\n[1] 取得 TWSE 即時清單...")
    stock_list, total_raw = get_stock_list()
    phase0_n = len(stock_list)
    print(f"    Phase 0 通過：{phase0_n} 支")

    # Step 2: 技術篩選
    sample = stock_list if not CFG["trial_n"] else stock_list[:CFG["trial_n"]]
    n = len(sample)
    print(f"\n[2] 技術篩選（{'全市場' if not CFG['trial_n'] else f'試跑前{n}支'}）...")

    results = []; done = 0
    with ThreadPoolExecutor(max_workers=CFG["max_workers"]) as ex:
        futures = {ex.submit(screen, s): s for s in sample}
        for fut in as_completed(futures):
            done += 1
            r = fut.result()
            if r: results.append(r)
            if done % 50 == 0:
                print(f"    進度 {done}/{n}  候選 {len(results)} 支")
            time.sleep(0.1)

    # Step 3: 排序輸出
    if results:
        df_out = pd.DataFrame(results).sort_values("R:R", ascending=False)
    else:
        df_out = pd.DataFrame()

    csv_path = f"/tmp/台股選股_{TODAY}.csv"
    if not df_out.empty:
        df_out.to_csv(csv_path, index=False, encoding="utf-8-sig")

    elapsed = time.time() - t_start

    # Step 4: 報表輸出
    print(f"\n{'='*62}")
    print("  掃描報告")
    print(f"{'='*62}")
    print(f"  TWSE 股票原始              : {total_raw}")
    print(f"  [P0] 排除 ETF/5碼          : {stats['etf']}")
    print(f"  [P0] 排除金融保險          : {stats['finance']}")
    print(f"  [P0] 排除電信（通信網路）   : {stats['telecom']}")
    print(f"  [P0] 排除紡織              : {stats['textile']}")
    print(f"  [P0] 排除成交量<1000張     : {stats['vol']}")
    print(f"  [P0] Phase 0 通過          : {phase0_n}")
    print(f"  [P0] 排除 BIAS 不符        : {stats['bias']}")
    print(f"  [P1-A] 排除均線未聚攏      : {stats['p1_ma']}")
    print(f"  [P1-B] 排除 MACD 未趨0     : {stats['p1_macd']}")
    print(f"  [P1-C] 排除 ADX 過高       : {stats['p1_adx']}")
    print(f"  [P1-H] 排除縮軌不符(日+週) : {stats['p1_bbw']}")
    print(f"  [P2-F] 排除量能不足        : {stats['p2_vol']}")
    print(f"  [P2-G] 排除 K 棒不符       : {stats['p2_candle']}")
    print(f"  [ERR]  資料不足/失敗        : {stats['err']}")
    print(f"  ★ 最終候選股              : {stats['final']}")
    print(f"  ⏱  耗時                    : {elapsed:.0f} 秒")
    print(f"{'='*62}")

    if results:
        print(f"\n  {'代號':<6}{'名稱':<10}{'產業':<12}{'收盤':<8}{'停損':<8}{'risk%':<8}{'R:R'}")
        print("  " + "-"*58)
        for r in (df_out.to_dict("records") if not df_out.empty else []):
            print(f"  {r['代號']:<6}{r['名稱']:<10}{r['產業'][:10]:<12}"
                  f"{r['收盤']:<8}{r['sl_final']:<8}{r['risk%']:<8}{r['R:R']}")

    # Step 5: 發送 Email
    print("\n[3] 發送 Email 報告...")
    has_result = stats["final"] > 0
    subject = (f"【台股選股】{TODAY_DISP} 候選股 {stats['final']} 支 🎯"
               if has_result else
               f"【台股選股】{TODAY_DISP} 今日無候選股")

    html = build_html(
        results=df_out.to_dict("records") if not df_out.empty else [],
        stats_snap=dict(stats),
        total_raw=total_raw,
        phase0_n=phase0_n,
        elapsed=elapsed,
    )
    send_email(subject, html, csv_path if not df_out.empty else None)
    print("\n✅ 完成")


if __name__ == "__main__":
    # 試跑：掃描前 80 支
    CFG["trial_n"] = 80
    main()
