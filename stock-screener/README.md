# 台股蓄勢待噴選股系統 v6

每個交易日 **13:30（台灣時間）** 自動掃描全市場，結果 Email 寄出。

## 篩選架構（七重條件）

| 階段 | 條件 | 門檻 |
|------|------|------|
| Phase 0 ① | 排除 ETF | 代號首碼 "0" |
| Phase 0 ② | 排除金融保險 | 產業代號 17 |
| Phase 0 ③ | 排除電信 | 通信網路業 |
| Phase 0 ④ | 排除紡織 | 紡織纖維業 |
| Phase 0 ⑤ | 市值 ≥ 20 億 | 排除小型股 |
| Phase 0 ⑥ | 成交量 ≥ 1,000 張 | 流動性過濾 |
| Phase 0 ⑦ | BIAS 三線合一 | MA6/12/24 乖離率 |
| Phase 1 A | 均線聚攏 | MA20/60/120/240 spread < 5% |
| Phase 1 B | MACD 趨近 0 | Histogram < 0.05 |
| Phase 1 C | ADX < 14 | 多空均弱，蓄勢中 |
| Phase 1 H1 | 日線縮軌 | BBW < MA20 × 0.8 且近3日遞縮 |
| Phase 1 H2 | 週線縮軌 | BBW < MA10 × 0.8 且近2週遞縮 |
| Phase 2 F | 量能突增 | 量 > 5日均量 × 1.5（F1必要）|
| Phase 2 G | K棒確認 | 收紅站上MA20，實體>40%，上影<30% |
| Stop Loss | 三方法取最寬 | ATR×2 / 近期低點 / MA20×0.98 |

## 部署步驟

### 1. 設定 GitHub Secrets

前往 `Vivian-agent` → Settings → Secrets and variables → Actions → New repository secret

| Secret 名稱 | 值 |
|---|---|
| `GMAIL_USER` | 你的 Gmail（xxx@gmail.com）|
| `GMAIL_APP_PWD` | Gmail 應用程式密碼（16碼）|
| `MAIL_TO` | 收件人 Email（可多個逗號分隔）|

### 2. Gmail 應用程式密碼

Google 帳號 → 安全性 → 兩步驟驗證（先開啟）→ 應用程式密碼 → 選「郵件」→ 產生

### 3. 排程說明

- 自動排程：每週一至五，台灣時間 **13:30**（cron: `30 5 * * 1-5`）
- 手動觸發：GitHub Actions → `台股蓄勢選股` → Run workflow

### 4. 本機執行

```bash
cd stock-screener
pip install -r requirements.txt
python stock_screener_v6.py
```

## 輸出

- 終端機：篩選漏斗統計 + 候選股列表
- Email：HTML 格式報告 + CSV 附件
- Artifact：result_YYYYMMDD.csv（保留 30 天）
