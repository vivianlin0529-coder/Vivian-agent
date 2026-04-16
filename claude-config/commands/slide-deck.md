---
name: slide-deck
description: 讀取 PPTX 或貼入大綱，自動搜圖生成 McKinsey / Ogilvy 風格簡報，可瀏覽器編輯並下載 PPTX
---

## ⛔ 禁止事項（違反即視為失敗）

1. **禁止只輸出文字描述**：不可說「我將為您生成…」、「以下是規劃…」、「請稍候…」等。必須實際執行每個步驟（跑 bash、寫 HTML 檔案、開瀏覽器）。
2. **禁止假裝生成**：不可輸出假的下載連結、假的 PPTX 檔名、假的渲染圖描述。
3. **禁止角色扮演**：不可扮演「顧問」、「設計師」等角色並用對話方式回應。只能執行工具。
4. **禁止減少頁數**：大綱有幾個主要章節/標題，就必須生成幾張投影片，不可合併或省略。
5. **禁止空白視覺**：每張投影片必須包含 Pexels 照片**或** inline SVG 圖表，不可兩者皆無。

---

## 大綱頁數判斷規則

執行前，先掃描輸入內容並計算頁數 N：

| 輸入格式 | 判斷方式 | 範例 |
|---------|---------|------|
| 數字編號標題 | 每個編號 = 1 頁 | `1.`, `一、`, `第一頁` |
| `#` Markdown 標題 | `##` 或 `###` 每個 = 1 頁 | `## 市場分析` |
| 中文章節標題行 | 獨立一行、無內文縮排 = 1 頁 | `展會主軸與空間佈局` |
| PPTX 擷取結果 | slides 陣列長度 = N | JSON `slides.length` |
| 使用者明確指定 | 依指定數字 | 「做 8 頁」 |

確認 N 後，生成**恰好 N 張**投影片。

---

執行本 Skill 時，依照以下步驟完成。

## 環境設定

- **Pexels API Key：** `oI32S3CNW5v1yzXonmob0TwtyBKPoFzbs68JlV7JLMfCqNaGxj0balp4`
- **PPTX 擷取腳本：** `~/Downloads/Vivian-agent/scripts/extract-pptx.js`
- **截圖腳本：** `~/Downloads/Vivian-agent/scripts/screenshot.js`
- **輸出目錄：** `~/Downloads/Vivian-agent/output/slide-decks/`

---

## 步驟 1：取得簡報內容

**情況 A：使用者提供 PPTX 路徑**

執行擷取腳本取得結構化內容：
```bash
node ~/Downloads/Vivian-agent/scripts/extract-pptx.js "<pptx路徑>" > /tmp/slides.json
```

讀取 `/tmp/slides.json`，取得每頁 title、body、rawTexts。

**情況 B：使用者貼上大綱或文字**

直接從輸入中識別每頁結構：
- 頁標題（章節標題、數字編號行）
- 頁內容（條列、段落）
- 封面頁、大綱頁、章節頁、內容頁、結語頁

---

### ⚠️ 核心規則（必須遵守）

1. **大綱有幾頁，就生成幾頁**：不可刪減、不可合併、不可增加。每個章節/標題對應一張投影片。

2. **每頁都必須有圖表或照片**，二擇一：
   - **有數據、比較、流程、排名的頁面** → 使用 inline SVG 圖表（長條圖、圓餅圖、折線圖、時間軸、漏斗圖等）
   - **敘事、情境、品牌、封面頁面** → 使用 Pexels 實拍照片作為背景
   - 若一頁同時有數據與情境 → 照片背景 + SVG 圖表疊加

3. **圖表選擇邏輯**：
   | 內容類型 | 建議圖表 |
   |---------|---------|
   | 數字比較 / 市場規模 | 長條圖（inline SVG `<rect>`） |
   | 佔比 / 份額 | 環圈圖（SVG `stroke-dasharray`） |
   | 時間進程 / 里程碑 | 時間軸（CSS flexbox + 節點） |
   | 流程 / 動線 | 流程箭頭圖（SVG `<polygon>`） |
   | 多項目列舉 | 圖示卡片（Unicode icon + 色塊） |
   | 排名 / 優先順序 | 橫向條狀圖（CSS width%） |

---

## 步驟 2：確認設定

若使用者未指定，詢問：
1. **風格**：McKinsey（白底、顧問型）或 Ogilvy（實拍照片、公關創意型）？
2. **比例**：16:9（1280×720）或 4:3（960×720）？

---

## 步驟 3：取得台北時間

執行 `date` 確認今日日期，取 YYYYMMDD 格式。

---

## 步驟 4：每頁搜尋 Pexels 照片

針對每張投影片的主題，用 Pexels API 搜尋實體照片：

```bash
curl -s -H "Authorization: oI32S3CNW5v1yzXonmob0TwtyBKPoFzbs68JlV7JLMfCqNaGxj0balp4" \
  "https://api.pexels.com/v1/search?query=英文關鍵字&per_page=1&orientation=landscape&size=large" \
  | node -e "let d='';process.stdin.on('data',c=>d+=c);process.stdin.on('end',()=>{const j=JSON.parse(d);console.log(j.photos[0].src.original);})"
```

每張投影片用 2–3 個英文關鍵字，對應該頁主題。

---

## 步驟 5：建立輸出目錄

```bash
mkdir -p ~/Downloads/Vivian-agent/output/slide-decks/YYYYMMDD_簡報標題/
```

---

## 步驟 6：生成 HTML 簡報

生成完整 HTML 檔案，儲存至輸出目錄的 `index.html`。

### HTML 規格

**必要功能：**
- 支援 McKinsey 和 Ogilvy 雙風格（CSS class 切換）
- 支援 16:9 和 4:3 比例切換
- 左側控制面板：風格切換、比例切換、文字大小滑桿、遮罩深度、縮圖列
- 所有文字使用 `contenteditable="true"` 可直接點擊編輯
- 鍵盤左右鍵導覽投影片
- 截圖模式按鈕（隱藏控制面板）
- pptxgenjs 一鍵下載 PPTX（CDN: `https://cdn.jsdelivr.net/npm/pptxgenjs@3.12.0/dist/pptxgen.bundle.js`）

**投影片類型：**
- `cover`：封面頁（McKinsey 深藍底、Ogilvy 全幅照片）
- `section`：章節分隔頁
- `content`：一般內容頁（標題 = insight，內文 = 條列說明）
- `qa`：Q&A 結語頁
- 每頁帶 `data-photo` 屬性存放 Pexels 圖片 URL

---

### 內容頁必備三層結構（content 類型）

每張 content 投影片**必須**包含：

```
① slide-headline  — 一句話結論（加大、加粗、顯眼色，McKinsey 用 accent 底線）
② slide-points    — 三個次標論述（每點 = 小標題 + 1-2 行說明）
③ slide-chart     — 圖表或圖示區（右側或底部，視版型而定）
```

HTML 範例：
```html
<div class="slide-headline" contenteditable="true">
  台灣可信賴 ICT 次系統需求 3 年成長 2.4 倍
</div>
<div class="slide-points">
  <div class="point">
    <div class="point-title" contenteditable="true">▸ 美中對抗加速去中化</div>
    <div class="point-body"  contenteditable="true">川普關稅政策推動供應鏈移轉，「可信賴來源」成核心採購條件</div>
  </div>
  <div class="point">
    <div class="point-title" contenteditable="true">▸ AI 智慧製造擴大次系統需求</div>
    <div class="point-body"  contenteditable="true">全球 AI 與智慧製造浪潮驅動感測、通訊、HMI 模組需求大幅擴張</div>
  </div>
  <div class="point">
    <div class="point-title" contenteditable="true">▸ 台灣 ICT 具不可取代優勢</div>
    <div class="point-body"  contenteditable="true">半導體、感測、通訊模組完整生態，全球客戶認可度持續提升</div>
  </div>
</div>
<div class="slide-chart">
  <!-- 此處放 inline SVG 圖表或圖示 -->
</div>
```

---

### 圖表與圖示規範

**圖表類型（依頁面主題選擇）：**

| 類型 | 適用場景 | 實作方式 |
|------|---------|---------|
| 長條圖 | 比較數據、市場規模 | inline SVG `<rect>` |
| 橫向條狀 | 進度、比例、排名 | CSS `width %` + 色塊 |
| 圓餅 / 環圈圖 | 佔比、份額 | SVG `<circle>` stroke-dasharray |
| 折線趨勢圖 | 成長趨勢、時間序列 | SVG `<polyline>` |
| 漏斗圖 | 轉化流程、篩選 | SVG `<polygon>` |
| 圖示卡片 | 列舉項目、特色 | Unicode 或 SVG icon + 文字 |
| 時間軸 | 階段推進、里程碑 | CSS flexbox + 節點圓點 |
| 熱力矩陣 | 優先順序、策略定位 | CSS grid + 色彩深淺 |

**常用 SVG 圖示（直接嵌入）：**
- 🌐 國際連結：地球圖示
- 🏭 製造：齒輪 / 工廠
- 🤝 合作：握手
- 📈 成長：上升箭頭
- 🔒 可信賴：盾牌
- ⚙️ 技術：齒輪
- 🚀 創新：火箭

**圖表設計原則：**
- McKinsey 風格：線條簡潔，配色用 navy / accent / light，加數字標注
- Ogilvy 風格：白色半透明圖表，疊加在照片背景上
- 每張圖表必須有標題與單位
- 數字要醒目（加大字體、加粗）

---

### McKinsey 設計規範

- 白色背景，頂部漸層色條（navy → blue → accent）
- 左側加電藍色（#00A8E8）直線作視覺錨點
- **slide-headline**：accent 色底線、字體加大、置於標題下方
- **slide-points**：三欄或三列，每點帶小標題
- **slide-chart**：右側 40% 寬，或底部橫幅區
- 頁面底部：品牌名稱（左）+ 頁碼（右）

### Ogilvy 設計規範

- 全幅實拍照片底圖
- 漸層深色遮罩（左深右淺）
- 超大白色粗體標題（衝擊感）
- **slide-headline**：金色（#F5A623）文字，置於標題下方
- **slide-points**：左側三點，白色半透明卡片
- **slide-chart**：右側半透明白色圖表
- 右下角頁碼

**參考範例：**
見 `~/Downloads/Vivian-agent/output/slide-decks/20260415_關鍵產業國際供應鏈計畫/index.html`

---

## 步驟 7：開啟瀏覽器預覽

```bash
# Windows
start ~/Downloads/Vivian-agent/output/slide-decks/YYYYMMDD_標題/index.html
```

---

## 步驟 8：回報結果

回報：
- 投影片數量
- 輸出路徑
- 可用操作說明（鍵盤導覽、編輯、PPTX 下載、截圖）

---

## 使用說明（每次執行完後告知使用者）

```
操作說明：
・鍵盤 ← → 切換投影片
・點擊文字直接編輯
・左側面板切換 McKinsey / Ogilvy 風格
・左側面板切換 16:9 / 4:3 比例
・點「下載 PPTX」直接存檔
・點「截圖模式」隱藏面板後，執行截圖：
  node ~/Downloads/Vivian-agent/scripts/screenshot.js \
    ~/Downloads/Vivian-agent/output/slide-decks/資料夾/index.html
```
