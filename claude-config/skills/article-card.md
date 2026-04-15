---
name: article-card
description: 將文章內容製作成 1920x1080 科技風圖片卡片，自動截圖輸出 PNG
---

執行本 Skill 時，依照以下完整步驟完成任務。

## 環境設定

- **Pexels API Key：** `oI32S3CNW5v1yzXonmob0TwtyBKPoFzbs68JlV7JLMfCqNaGxj0balp4`
- **截圖腳本：** `~/Downloads/Vivian-agent/scripts/screenshot.js`
- **輸出目錄：** `~/Downloads/Vivian-agent/output/article-cards/`

---

## 步驟 1：確認輸入

使用者會透過 args 或對話提供文章文字內容。

**若使用者同時提供圖片路徑（自訂模板）**：讀取該圖片，分析其版面配置、色調、元素位置，作為 HTML 設計依據。

**若未提供圖片**：根據文章主題，用 Pexels API 自動搜尋適合的實體照片：

```bash
curl -s -H "Authorization: oI32S3CNW5v1yzXonmob0TwtyBKPoFzbs68JlV7JLMfCqNaGxj0balp4" \
  "https://api.pexels.com/v1/search?query=關鍵字&per_page=1&orientation=landscape&size=large" \
  | node -e "let d='';process.stdin.on('data',c=>d+=c);process.stdin.on('end',()=>{const j=JSON.parse(d);console.log(j.photos[0].src.original);})"
```

- 關鍵字：從文章標題 / 摘要提取 2–3 個英文關鍵字（例：`smart factory AI robot`）
- 取得圖片 URL 後，用於 HTML 背景圖（搭配 Pexels 圖片參數：`?auto=compress&cs=tinysrgb&w=1920&h=1080&fit=crop`）

---

## 步驟 2：擷取標題與摘要

從文章內容中識別：

- **標題**：文章第一行，或明顯標記為標題的段落
- **摘要**：內文前 80–120 字（中文約 40–60 字）；若文章有明確摘要段落則優先使用

---

## 步驟 3：取得台北時間

執行 `date` 指令確認今日台北時間，取得 YYYYMMDD 格式日期。

---

## 步驟 4：生成 1920x1080 HTML

生成一個完整 HTML 文件，規格如下：

### 設計規範（預設科技風）

| 元素 | 規格 |
|------|------|
| 背景色 | `#0a0e1a`（深海軍藍） |
| 主要強調色 | `#00d4ff`（電藍） |
| 次要強調色 | `#7b61ff`（科技紫） |
| 標題顏色 | `#ffffff` |
| 摘要顏色 | `#b8c5d6` |
| 標題字體大小 | 60–72px |
| 摘要字體大小 | 28–32px |
| 行高 | 1.6–1.8 |
| 版面留白 | 上下各 100px，左右各 160px |

### 視覺元素

- 左上角或底部加入細線/光暈裝飾（用 CSS border 或 box-shadow 實作）
- 右側或背景加入半透明幾何網格（用 CSS linear-gradient 或 SVG 實作）
- 標題上方加入一條 3px 電藍色橫線作為視覺錨點
- 右下角加入日期標記（小字，半透明）

### HTML 技術要求

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    /* 在此定義所有樣式，不依賴外部 CSS 檔案 */
    /* 字體使用 @import Google Fonts：Inter + Noto Sans TC */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Noto+Sans+TC:wght@400;500;700&display=swap');
    
    html, body {
      width: 1920px;
      height: 1080px;
      margin: 0;
      overflow: hidden;
    }
  </style>
</head>
<body>
  <!-- 內容 -->
</body>
</html>
```

- 所有樣式寫在 `<style>` 標籤內（不使用外部 CSS）
- 文字設定 `word-break: break-word; overflow-wrap: break-word;`
- 標題超過兩行需縮小字體，確保不溢出版面

---

## 步驟 5：儲存 HTML 檔案

**輸出目錄**：`/Users/vivianlin/Downloads/Vivian-agent/output/article-cards/`

若目錄不存在，先執行 `mkdir -p` 建立。

**檔名格式**：`YYYYMMDD_文章標題.html`
- 日期取自步驟 3
- 標題去除空格（改為底線）與特殊符號（`/ \ : * ? " < > |`）
- 範例：`20260415_AI驅動的智慧製造趨勢.html`

使用 Write 工具儲存 HTML 至上述路徑。

---

## 步驟 6：自動截圖

使用 Bash 執行截圖腳本（Node.js + Puppeteer）：

```bash
node /Users/vivianlin/Downloads/Vivian-agent/scripts/screenshot.js "<HTML檔案完整路徑>"
```

腳本位於：`/Users/vivianlin/Downloads/Vivian-agent/scripts/screenshot.js`
截圖會自動儲存為同名 `.png` 檔案。

---

## 步驟 7：回報結果

回報：
- HTML 檔案完整路徑
- PNG 截圖完整路徑
- 標題與摘要預覽（確認擷取正確）

---

## 注意事項

- 字體若因網路問題無法載入，改用 `system-ui, -apple-system, 'Helvetica Neue', sans-serif`
- 若使用者有提供模板圖片，讀取圖片後優先依圖片配色與排版設計，覆蓋預設規範
- 台北時間（Asia/Taipei, UTC+8）
