# GitHub Secrets 設定指引

前往 GitHub → `vivianlin0529-coder/Vivian-agent` → Settings → Secrets and variables → Actions → New repository secret

## 必填 Secrets

| Secret 名稱 | 說明 | 取得方式 |
|------------|------|----------|
| `ANTHROPIC_API_KEY` | Claude API Key | https://console.anthropic.com → API Keys |
| `ELEVENLABS_API_KEY` | ElevenLabs API Key | 已在 .env：`sk_e641...` |
| `ELEVENLABS_VOICE_ID` | 語音 ID | 已在 .env：`oGcfKz3pBlkD56OfrAe5` |
| `YOUTUBE_API_KEY` | YouTube Data API Key（搜尋用） | 見下方步驟 |
| `YOUTUBE_TOKEN_B64` | YouTube OAuth Token（上傳用）| 見下方步驟 |
| `NOTION_TOKEN` | Notion Integration Token | 見下方步驟 |
| `NOTION_VIDEO_DB` | 參考影片資料庫 ID | 見下方步驟 |
| `GOOGLE_CLIENT_SECRET` | client_secret.json 的 JSON 內容 | 已有，複製貼上即可 |
| `GMAIL_TOKEN_JSON` | Gmail OAuth Token（base64）| 見下方步驟 |

---

## 取得 YouTube API Key（搜尋用）

1. 前往 https://console.cloud.google.com/apis/library?project=phonic-operand-313001
2. 搜尋「YouTube Data API v3」→ 啟用
3. 前往「憑證」→「建立憑證」→「API 金鑰」
4. 複製金鑰填入 `YOUTUBE_API_KEY`

---

## 取得 YOUTUBE_TOKEN_B64（上傳用）

在**家用電腦**執行（已有 token.pickle）：

```bash
cd "C:/Users/Vivi/Documents/My project/Vivian-agent"
python -c "
import base64
with open('token.pickle','rb') as f:
    print(base64.b64encode(f.read()).decode())
"
```

複製輸出的 base64 字串 → 填入 `YOUTUBE_TOKEN_B64`

---

## 取得 Notion Token

1. 前往 https://www.notion.so/my-integrations
2. 點「New integration」→ 名稱：`Vivi Agent`
3. 複製「Internal Integration Token」→ 填入 `NOTION_TOKEN`
4. 在 Notion 的「AI × 個人品牌變現藍圖」資料庫頁面 → 右上「...」→「Add connections」→ 選 Vivi Agent

---

## 取得 NOTION_VIDEO_DB

1. 打開「AI × 個人品牌變現藍圖」資料庫
2. 在瀏覽器 URL 複製資料庫 ID（32 位英數字串）
3. 填入 `NOTION_VIDEO_DB`

---

## 設定完成後測試

前往 GitHub Actions → 手動觸發 workflow：
- `🌅 Vivi 每日晨報` → Run workflow
- `🎬 Vivi 每日影片自動生成` → Run workflow（可選填主題）

---

## 自動執行時間

| Workflow | 台灣時間 | UTC Cron |
|---------|---------|---------|
| 每日晨報 | 週一到週五 08:00 | `0 0 * * 1-5` |
| 每日影片 | 每天 22:00 | `0 14 * * *` |
