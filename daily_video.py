"""
Vivi AI研習社 — 每日影片自動生產流程
輸出：16:9 YouTube 標準教學影片（步驟圖卡 + 實際截圖）

EXECUTION_MODE:
  PREVIEW（預設）— 生成影片但不上傳 YouTube，輸出 daily_preview_video.mp4 供確認
  FULL           — 重新生成並上傳 YouTube
"""

import os, re, json, datetime, base64, time, pickle, shutil
from pathlib import Path
import requests
from google import genai as genai_sdk
from google.genai import types as genai_types

# ── 執行模式 ──────────────────────────────────────────────────────
EXECUTION_MODE = os.environ.get("EXECUTION_MODE", "PREVIEW").upper()
print(f"\n⚙️  執行模式：{EXECUTION_MODE}")

# ── 環境變數 ──────────────────────────────
GEMINI_KEY       = os.getenv("GEMINI_API_KEY", "")
GOOGLE_TTS_KEY   = os.getenv("YOUTUBE_API_KEY", "")
# ✅ 修改：改用 Neural2 引擎，聽起來更接近真人台灣女聲
GOOGLE_TTS_VOICE = os.getenv("GOOGLE_TTS_VOICE", "cmn-TW-Wavenet-A")
YOUTUBE_API_KEY  = os.getenv("YOUTUBE_API_KEY", "")
NOTION_TOKEN     = os.getenv("NOTION_TOKEN", "")
NOTION_VIDEO_DB  = os.getenv("NOTION_VIDEO_DB", "")

# GitHub Actions：從 base64 secret 還原 YouTube token
_yt_b64 = os.getenv("YOUTUBE_TOKEN_B64", "")
if _yt_b64:
    with open("token.pickle", "wb") as _f:
        _f.write(base64.b64decode(_yt_b64))

def _require(name, value):
    if not value:
        raise EnvironmentError(f"❌ 缺少環境變數：{name}")

_require("GEMINI_API_KEY", GEMINI_KEY)
_require("YOUTUBE_API_KEY", GOOGLE_TTS_KEY)

# ── Gemini 初始化 ─────────────────────────
gemini = genai_sdk.Client(api_key=GEMINI_KEY)
GEMINI_MODEL = "gemini-2.5-flash"

# ── 共用工具 ──────────────────────────────
def _gemini_json(prompt: str, use_search: bool = False, array: bool = False):
    config_kwargs = {}
    if use_search:
        config_kwargs["tools"] = [genai_types.Tool(google_search=genai_types.GoogleSearch())]
    else:
        config_kwargs["response_mime_type"] = "application/json"
    config = genai_types.GenerateContentConfig(**config_kwargs)
    for attempt in range(3):
        try:
            msg = gemini.models.generate_content(
                model=GEMINI_MODEL, contents=prompt, config=config)
            text = msg.text
            pattern = r'\[[\s\S]+\]' if array else r'\{[\s\S]+\}'
            match = re.search(pattern, text)
            if match:
                return json.loads(match.group())
            return [] if array else {}
        except Exception as e:
            print(f"  ⚠️ Gemini 第 {attempt+1} 次失敗：{e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
    return [] if array else {}

def _safe_post(url, *, headers, json_body=None, timeout=60):
    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=json_body, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            print(f"  ⚠️ 請求第 {attempt+1} 次失敗：{e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise

# ═══════════════════════════════════════════
# 任務一：對標帳號研究
# ═══════════════════════════════════════════
def research_benchmark_accounts() -> dict:
    print("\n🔍 任務一：搜尋對標帳號...")
    prompt = """
你是 Vivi AI研習社的內容策略師。請用 Google 搜尋，列出 AI 工具教學 & AI 變現領域的真實對標帳號。
英文帳號（3個）：訂閱數 10 萬以上、以「非工程師也能用 AI」或「AI 副業」為主。
日文帳號（3個）：近期活躍、主題為「AI活用」「AI副業」。
每個附：帳號名稱、YouTube 頻道 URL、定位一句話、代表影片標題
輸出 JSON：
{"english":[{"name":"...","url":"...","positioning":"...","sample_video":"..."}],
 "japanese":[{"name":"...","url":"...","positioning":"...","sample_video":"..."}]}
"""
    result = _gemini_json(prompt, use_search=True)
    print(f"  英文帳號：{len(result.get('english',[]))} 個 / 日文帳號：{len(result.get('japanese',[]))} 個")
    return result

# ═══════════════════════════════════════════
# 選題歷史記錄（每日 Top5 + 已發布）
# ═══════════════════════════════════════════
USED_TOPICS_FILE   = "used_topics.json"
TOPIC_RANKING_FILE = "topic_rankings.json"

def load_used_topics() -> list:
    """已發布的選題標題清單（過去 60 天）"""
    if not Path(USED_TOPICS_FILE).exists():
        return []
    try:
        with open(USED_TOPICS_FILE, encoding="utf-8") as f:
            records = json.load(f)
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=60)).isoformat()
        return [r["title"] for r in records if r.get("date", "") >= cutoff]
    except Exception:
        return []

def save_used_topic(title: str):
    """記錄本次已發布的選題"""
    records = []
    if Path(USED_TOPICS_FILE).exists():
        try:
            with open(USED_TOPICS_FILE, encoding="utf-8") as f:
                records = json.load(f)
        except Exception:
            records = []
    records.append({"title": title, "date": datetime.datetime.now().isoformat()})
    records = records[-120:]
    with open(USED_TOPICS_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"  📚 已發布選題記錄更新（共 {len(records)} 筆）")

def save_daily_top5(topics: list):
    """儲存今日 Top5 候選到排名歷史"""
    records = []
    if Path(TOPIC_RANKING_FILE).exists():
        try:
            with open(TOPIC_RANKING_FILE, encoding="utf-8") as f:
                records = json.load(f)
        except Exception:
            records = []
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    # 移除今天的舊資料（若重跑）
    records = [r for r in records if r.get("date") != today]
    records.append({
        "date": today,
        "topics": [{"title": t.get("title",""), "score": t.get("score",0),
                    "tool": t.get("tool",""), "keyword": t.get("keyword","")}
                   for t in topics[:5]]
    })
    # 只保留最近 30 天
    records = records[-30:]
    with open(TOPIC_RANKING_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"  📊 今日 Top5 已存入排名歷史")

def load_past_rankings(days: int = 3) -> list:
    """讀取過去 N 天的排名歷史（不含今天）"""
    if not Path(TOPIC_RANKING_FILE).exists():
        return []
    try:
        with open(TOPIC_RANKING_FILE, encoding="utf-8") as f:
            records = json.load(f)
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        return [r for r in records if cutoff <= r.get("date","") < today]
    except Exception:
        return []

def _title_similar(a: str, b: str, threshold: float = 0.55) -> bool:
    """判斷兩個標題是否相似（字元集重疊率）"""
    ca, cb = set(a), set(b)
    if not ca:
        return False
    return len(ca & cb) / len(ca) > threshold

def pick_best_topic(today_top5: list, past_rankings: list, used: list) -> dict:
    """
    三天排名交叉分析選出最佳選題：
    - 基礎分：今日 Gemini 評分（1-10）
    - 連續出現加分：過去 3 天每天出現 +2 分
    - 排名上升加分：今日排名比昨天高 +1 分
    - 已發布扣除：完全排除
    回傳最終最佳選題 dict
    """
    print("\n🏆 三天排名交叉分析...")

    # 建立今日排名 map（排名從 0 開始）
    today_rank = {t["title"]: i for i, t in enumerate(today_top5)}

    scored = []
    for rank_i, topic in enumerate(today_top5):
        title = topic.get("title", "")

        # 排除已發布
        if any(_title_similar(title, u) for u in used):
            print(f"  ⛔ 已發布，跳過：{title}")
            continue

        base   = topic.get("score", 5)
        bonus  = 0
        detail = []

        # 過去 3 天排名分析
        for day_rec in past_rankings:
            day_topics = day_rec.get("topics", [])
            for past_rank, pt in enumerate(day_topics):
                if _title_similar(title, pt.get("title", "")):
                    bonus += 2  # 連續出現
                    detail.append(f"{day_rec['date']} 排名#{past_rank+1}")
                    if past_rank > rank_i:   # 今天排名比那天更高 → 上升趨勢
                        bonus += 1
                        detail.append("↑ 上升趨勢")
                    break

        final = base + bonus
        scored.append({**topic, "final_score": final, "rank_detail": detail})
        trend_str = f"（過去出現：{', '.join(detail)}）" if detail else "（新題）"
        print(f"  {'★' if rank_i==0 else ' '} [{final}分 = 基礎{base}+加分{bonus}] {title} {trend_str}")

    if not scored:
        print("  ⚠️ 所有選題已發布，使用今日第一名（含已發布）")
        return today_top5[0] if today_top5 else {}

    scored.sort(key=lambda x: x["final_score"], reverse=True)
    best = scored[0]
    print(f"\n  ✅ 最終選題（{best['final_score']}分）：{best['title']}")
    return best

# 任務二：爆款選題分析
# ═══════════════════════════════════════════
def analyze_viral_topics(manual_topic: str = "", manual_tool: str = "") -> dict:
    print("\n💡 任務二：爆款選題分析（市場搜尋 + 三天趨勢交叉）...")
    if manual_topic:
        tool = manual_tool or "Claude"
        return {"title": manual_topic, "score": 10, "keyword": manual_topic,
                "appeal": "用戶指定", "algorithm": "手動選題", "reason": "手動指定",
                "tool": tool, "final_score": 10}

    used        = load_used_topics()
    past_ranks  = load_past_rankings(days=3)

    used_block = ""
    if used:
        used_list  = "\n".join(f"- {t}" for t in used[-30:])
        used_block = f"\n\n【已發布選題，完全避開】\n{used_list}"

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    prompt = f"""
今天是 {today}。你是「Vivi AI研習社」的內容策略師，請用 Google 搜尋台灣 AI 工具市場最新趨勢。

研究步驟：
1. 搜尋「台灣 AI 工具 職場 {today[:4]}」「AI 教學 上班族 短影片」
2. 搜尋 YouTube「AI工具教學」「ChatGPT教學」「Notion AI教學」近期爆款標題
3. 搜尋 PTT Soft_Job 板、Dcard 職場板 AI 工具最近熱門討論
4. 找最近 7 天有新功能或更新的 AI 工具（ChatGPT / Claude / Gemini / Notion AI / Canva AI / Gamma / Perplexity）

基於搜尋結果，提供 10 個爆款短影片候選選題，每個必須：
- 針對台灣非技術背景上班族（PM、業務、行政、主管）
- 具體 AI 工具操作教學，有 3 個可截圖的步驟
- 60 秒說清楚，標題含具體數字或成果
- 指定工具（Claude / Gamma / Notion AI / ChatGPT / Canva AI / Perplexity 等）{used_block}

輸出 JSON 陣列（10 個，依市場潛力評分 1-10，分數可重複）：
[{{"title":"...","appeal":"...","algorithm":"...","keyword":"...","tool":"...","score":9,"reason":"..."}}]
"""
    raw_topics = _gemini_json(prompt, use_search=True, array=True)
    if not raw_topics:
        raw_topics = [{"title": "3步驟用Claude整理會議記錄，省下2小時", "score": 9,
                       "keyword": "Claude 教學 會議記錄", "tool": "Claude",
                       "appeal": "具體省時數字", "algorithm": "搜尋量高", "reason": "fallback"}]

    raw_topics.sort(key=lambda x: x.get("score", 0), reverse=True)

    # 取今日 Top5（不排除已發布，排除留給 pick_best_topic 做）
    today_top5 = raw_topics[:5]
    print(f"  📋 今日 Top5 候選：")
    for i, t in enumerate(today_top5, 1):
        print(f"    {i}. [{t.get('score',0)}分] {t['title']} ({t.get('tool','')})")

    # 儲存今日 Top5 進排名歷史
    save_daily_top5(today_top5)

    # 三天交叉分析選出最佳
    best = pick_best_topic(today_top5, past_ranks, used)
    return best
# ═══════════════════════════════════════════
# 任務三：YouTube 參考影片搜尋
# ═══════════════════════════════════════════
def search_youtube_videos(keyword: str, max_results: int = 5) -> list:
    print(f"\n🎥 搜尋 YouTube 參考影片：{keyword}")
    if not YOUTUBE_API_KEY:
        print("  ⚠️ 未設定 YOUTUBE_API_KEY，跳過")
        return []
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={"part":"snippet","q":keyword,"type":"video","order":"viewCount",
                    "maxResults":max_results*2,"regionCode":"TW",
                    "relevanceLanguage":"zh-Hant","key":YOUTUBE_API_KEY}, timeout=20)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return []
        video_ids = ",".join([i["id"]["videoId"] for i in items])
        stats_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part":"statistics,snippet","id":video_ids,"key":YOUTUBE_API_KEY}, timeout=20)
        stats_resp.raise_for_status()
        stats_map = {v["id"]: v for v in stats_resp.json().get("items", [])}
        videos = []
        for item in items[:max_results]:
            vid_id = item["id"]["videoId"]
            stat = stats_map.get(vid_id, {})
            snippet = stat.get("snippet", item.get("snippet", {}))
            videos.append({
                "title": snippet.get("title",""),
                "channel": snippet.get("channelTitle",""),
                "views": int(stat.get("statistics",{}).get("viewCount",0)),
                "published_at": snippet.get("publishedAt","")[:10],
                "url": f"https://www.youtube.com/watch?v={vid_id}",
                "video_id": vid_id,
            })
        return sorted(videos, key=lambda x: x["views"], reverse=True)
    except Exception as e:
        print(f"  ⚠️ YouTube 搜尋失敗：{e}")
        return []

def analyze_video_outliers(videos: list, keyword: str) -> list:
    if not videos:
        return videos
    summary = json.dumps([{"title":v["title"],"views":v["views"]} for v in videos], ensure_ascii=False)
    prompt = f'分析 YouTube 關鍵字「{keyword}」熱門影片異常值原因。\n{summary}\n輸出 JSON 陣列：[{{"title":"...","outlier_reason":"..."}}]'
    analyses = _gemini_json(prompt, array=True)
    amap = {a["title"]: a.get("outlier_reason","") for a in analyses}
    for v in videos:
        v["outlier_reason"] = amap.get(v["title"],"")
    return videos

def write_to_notion(videos: list, benchmark: dict, topic_title: str):
    print("\n📝 寫入 Notion...")
    if not NOTION_TOKEN or not NOTION_VIDEO_DB:
        print("  ⚠️ 跳過（未設定 NOTION 環境變數）")
        return
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}",
                "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    for v in videos:
        pub_date = v.get("published_at","")
        page = {
            "parent": {"database_id": NOTION_VIDEO_DB},
            "properties": {
                "影片標題": {"title": [{"text":{"content": v["title"]}}]},
                "博主名稱": {"rich_text": [{"text":{"content": v["channel"]}}]},
                "播放量": {"number": v["views"]},
                "上傳日期": {"date": {"start": pub_date}} if pub_date else {"rich_text":[]},
                "影片連結": {"url": v["url"]},
                "異常值分析":{"rich_text": [{"text":{"content": v.get("outlier_reason","")}}]},
                "對應選題": {"rich_text": [{"text":{"content": topic_title}}]},
            }
        }
        try:
            resp = requests.post("https://api.notion.com/v1/pages",
                                 headers=headers, json=page, timeout=20)
            icon = "✅" if resp.status_code == 200 else f"❌{resp.status_code}"
            print(f"  {icon} {v['title'][:40]}")
        except Exception as e:
            print(f"  ❌ {e}")

# ═══════════════════════════════════════════
# 腳本生成（結構化教學步驟）
# ═══════════════════════════════════════════
def generate_script(topic: dict) -> tuple:
    print(f"\n✍️ 生成腳本：{topic['title']}")
    tool = topic.get("tool","Claude")
    prompt = f"""
你是 Vivi，台灣職場 AI 教學 YouTuber。製作一支口說＋畫面完全同步的教學影片。
選題：{topic['title']}  工具：{tool}

【重要限制】
- 禁止出現任何中文人名（用「主管」「客戶」「同事」「業務」代替）
- 每段旁白字數嚴格控制：pain旁白35字內、win旁白35字內、每步typing旁白25字、每步output旁白25字、cta旁白30字
- Prompt 範本必須直接可用，不能是說明文字
- 輸出範例要像真實 AI 輸出，有格式、有具體數字/日期/內容

【影片結構（共約55秒）】
- Hook Pain (7s)：說3個職場痛點（口說配信箱爆滿畫面）
- Hook Win  (7s)：說AI能帶來的3個改變（口說配整理好的輸出畫面）
- 每步驟 typing (7s)：說「輸入什麼指令」（口說配打字動畫）
- 每步驟 output (6s)：說「AI給了什麼結果」（口說配輸出串流）
- CTA (6s)：邀訂閱

輸出 JSON：
{{
  "title": "影片標題（25字內，含數字＋具體結果）",
  "description": "說明欄（含工具、情境、3步摘要、hashtag）",
  "tags": ["AI工具","Vivi AI研習社","職場效率"],
  "narration_pain": "痛點旁白（35字，描述3個具體職場痛點，不提人名）",
  "narration_win":  "成果旁白（35字，說明AI帶來的3個具體改變）",
  "narration_cta":  "結尾旁白（30字，問一個問題＋邀訂閱）",
  "pain_points": ["痛點1（15字內）","痛點2（15字內）","痛點3（15字內）","痛點4（15字內）"],
  "win_points":  ["成果1（15字內）","成果2（15字內）","成果3（15字內）","成果4（15字內）"],
  "steps": [
    {{
      "num": 1,
      "heading": "步驟標題（5字內）",
      "tool_name": "{tool}",
      "narration_type": "打字階段旁白（25字，說明輸入什麼指令、為什麼這樣寫）",
      "narration_out":  "輸出階段旁白（25字，說明AI給了什麼、有什麼用）",
      "url": "https://...",
      "action_label": "底部提示（16字內）",
      "bullets": ["動作1（8字）","動作2（8字）","預期結果（8字）"],
      "example_prompt": "完整Prompt（可直接貼用，4-5行，含背景+需求+格式+語氣，無人名）",
      "example_output": ["【AI輸出】","行2","行3","行4","行5","行6","行7"],
      "tip": "進階技巧（12字內）"
    }},
    {{"num":2,"heading":"步5字","tool_name":"{tool}","narration_type":"25字","narration_out":"25字","url":"https://...","action_label":"16字","bullets":["8字","8字","8字"],"example_prompt":"Prompt","example_output":["行1","行2","行3","行4","行5","行6"],"tip":"12字"}},
    {{
      "num": 3,
      "heading": "步5字",
      "tool_name": "{tool}",
      "is_slide_step": true,
      "narration_type": "25字，說明輸入什麼大綱或主題讓AI生成簡報",
      "narration_out": "25字，描述簡報已生成、有哪些張投影片、可直接使用",
      "url": "https://gamma.app",
      "action_label": "輸入主題 → AI生成 → 下載",
      "bullets": ["輸入主題大綱（8字）","AI 生成投影片（8字）","直接下載使用（8字）"],
      "example_prompt": "Step3 的 Prompt：請生成一份簡報，主題為「XXX」，對象為「職場上班族」，共5張，風格專業簡潔，每張含標題和3個重點",
      "example_output": ["【AI 生成大綱】","第1張：主題說明","第2張：現況分析","第3張：解決方案","第4張：執行步驟","第5張：結論與行動"],
      "tip": "加「對象+張數」讓簡報更精準"
    }}
  ]
}}
"""
    data  = _gemini_json(prompt)
    steps = data.get("steps",[])
    title = data.get("title", topic["title"])
    desc  = data.get("description","")
    tags  = data.get("tags",["AI工具","Vivi AI研習社"])

    if steps:
        steps[0]["pain_points"] = data.get("pain_points",[])
        steps[0]["win_points"]  = data.get("win_points",[])

    # 把各段旁白存入 steps 結構方便後續使用
    narrations = {
        "pain": data.get("narration_pain",""),
        "win":  data.get("narration_win",""),
        "cta":  data.get("narration_cta",""),
    }
    for s2 in steps:
        narrations[f"step{s2['num']}_type"] = s2.get("narration_type","")
        narrations[f"step{s2['num']}_out"]  = s2.get("narration_out","")

    print(f"  步驟：{len(steps)}")
    for s2 in steps:
        print(f"    Step {s2.get('num')}: {s2.get('heading')} | prompt={len(s2.get('example_prompt',''))}字")
    # 回傳完整旁白（供 TTS 備用）+ steps + narrations dict
    full = "\n".join(narrations.values())

    # ── 實際執行每個步驟的 Prompt，取得真實 AI 輸出 ──
    print("\n🤖 執行各步驟 Prompt，取得真實 AI 輸出...")
    for _s in steps:
        _ep = _s.get("example_prompt","")
        _tool = _s.get("tool_name","Claude")
        if _ep and not _s.get("is_slide_step"):
            print(f"  Step {_s['num']} [{_tool}] 執行中...")
            _real = _get_real_ai_output(_ep, _tool)
            if _real:
                _s["example_output"] = _real

    return full, title, desc, tags, steps, narrations



def _get_real_ai_output(prompt: str, tool_name: str) -> list:
    """實際呼叫 Gemini 執行使用者 Prompt，取得真實 AI 輸出（分行）"""
    system = (
        f"你是 {tool_name} AI 助手，協助台灣職場上班族。\n"
        "請直接回覆請求，不要自我介紹。\n"
        "格式要求：\n"
        "- 使用繁體中文\n"
        "- 用條列、標題等清楚格式\n"
        "- 禁止出現任何真實人名（用主管/客戶/同事代替）\n"
        "- 回覆要具體，含數字、日期、格式\n"
        "- 長度：150-220字"
    )
    full_prompt = f"{system}\n\n使用者輸入：\n{prompt}"
    try:
        config = genai_types.GenerateContentConfig(
            response_mime_type="text/plain"
        )
        msg = gemini.models.generate_content(
            model=GEMINI_MODEL, contents=full_prompt, config=config)
        raw = msg.text.strip()
        import textwrap as tw2
        result = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            if len(line) <= 38:
                result.append(line)
            else:
                result.extend(tw2.wrap(line, width=36))
        print(f"    ✅ 真實 AI 輸出：{len(result)} 行")
        return result[:12]
    except Exception as e:
        print(f"    ⚠️ 真實輸出失敗：{e}")
        return []

def capture_screenshots(steps: list) -> dict:
    """已停用：改用動態範例渲染"""
    return {}


# ═══════════════════════════════════════════
# 語音生成（分段 TTS，每段對應一個視覺段落）
# ═══════════════════════════════════════════
def generate_voice_segments(narrations: dict) -> dict:
    """為每個旁白段落生成獨立 mp3，回傳 {segment_name: file_path}"""
    import asyncio, edge_tts
    VOICE = "zh-TW-HsiaoChenNeural"
    VOICE2= "zh-TW-HsiaoYuNeural"
    seg_files = {}

    async def _tts(text, path, voice):
        comm = edge_tts.Communicate(text=text, voice=voice, rate="+0%", volume="+0%")
        await comm.save(path)

    for seg_name, text in narrations.items():
        if not text.strip():
            continue
        path = f"seg_{seg_name}.mp3"
        for voice in [VOICE, VOICE2]:
            try:
                asyncio.run(_tts(text, path, voice))
                size = Path(path).stat().st_size
                print(f"  ✅ {seg_name}: {path} ({size//1024} KB) [{voice.split('-')[-1]}]")
                seg_files[seg_name] = path
                break
            except Exception as ex:
                print(f"  ⚠️ {seg_name}/{voice}: {ex}")
    return seg_files


# ═══════════════════════════════════════════
# 影片渲染（分段音頻版）
# ═══════════════════════════════════════════
def render_video(seg_files: dict, steps: list,
                 title: str, output: str = "video_final.mp4") -> str:
    print("\n🎬 渲染影片（分段同步版）...")
    from video_renderer import render_tutorial_video
    return render_tutorial_video(seg_files, steps, title, output)


# ═══════════════════════════════════════════
# YouTube 上傳
# ═══════════════════════════════════════════
def upload_youtube(video_path: str, title: str, description: str, tags: list) -> str:
    print("📤 上傳 YouTube...")
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.auth.transport.requests import Request

    creds = None
    if Path("token.pickle").exists():
        with open("token.pickle", "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise EnvironmentError("YouTube token 無效，請重新授權並更新 YOUTUBE_TOKEN_B64 secret")

    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {"title": title[:100], "description": description[:5000],
                    "tags": tags, "categoryId": "28"},
        "status": {"privacyStatus": "public"},
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  上傳進度：{int(status.progress()*100)}%")
    url = f"https://youtu.be/{response['id']}"
    print(f"  ✅ 上傳完成：{url}")
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"youtube_url={url}\nvideo_title={title}\n")
    return url

# ═══════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════
def main():
    print(f"\n🚀 Vivi AI研習社 每日影片自動生產流程啟動")
    print(f"   {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} 台北時間")
    print(f"   模式：{'🔍 PREVIEW（只生成，不上傳）' if EXECUTION_MODE == 'PREVIEW' else '🚀 FULL（生成 + 上傳 YouTube）'}\n")

    manual_topic = os.getenv("MANUAL_TOPIC", "").strip()
    manual_tool  = os.getenv("MANUAL_TOOL",  "").strip()

    # ── 共同流程（PREVIEW & FULL 都執行）──
    benchmark = research_benchmark_accounts()
    best = analyze_viral_topics(manual_topic, manual_tool)
    if not best:
        best = {"title":"3步驟用Claude整理會議記錄","keyword":"Claude 教學","score":9,"tool":"Claude","final_score":9}

    print(f"\n  ✅ 今日最終選題（{best.get('final_score', best.get('score',0))}分）：{best['title']}")
    print(f"     工具：{best.get('tool','')} ｜ 關鍵字：{best.get('keyword','')} ｜ 亮點：{best.get('appeal','')}") 

    keyword = best.get("keyword") or best["title"]
    videos  = search_youtube_videos(keyword, max_results=5)
    if videos:
        videos = analyze_video_outliers(videos, keyword)
        write_to_notion(videos, benchmark, best["title"])

    # 記錄本次選題，避免未來重複
    save_used_topic(best["title"])

    narration, title, description, tags, steps, narrations = generate_script(best)
    seg_files = generate_voice_segments(narrations)

    date_str  = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    meta_path = "video_meta.json" if EXECUTION_MODE == "PREVIEW" else f"video_meta_{date_str}.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"title":title,"description":description,"tags":tags,
                   "steps":steps,"topic":best,"reference_videos":videos,
                   "mode": EXECUTION_MODE, "generated_at": date_str},
                  f, ensure_ascii=False, indent=2)
    print(f"  📄 Meta 儲存：{meta_path}")

    # audio generated per-segment above
    video_path = render_video(seg_files, steps, title)

    # ── 關鍵分岔點 ────────────────────────────────────
    if EXECUTION_MODE == "FULL":
        youtube_url = upload_youtube(video_path, title, description, tags)
        print(f"\n🎉 FULL 完成！影片已上架：{youtube_url}")
        return youtube_url
    else:
        preview_path = "daily_preview_video.mp4"
        shutil.copy(video_path, preview_path)
        print(f"\n✅ PREVIEW 完成！")
        print(f"   📦 影片：{preview_path}（請至 GitHub Actions → Artifacts 下載確認）")
        print(f"   📋 Meta：{meta_path}")
        print(f"   📌 確認無誤後，請手動觸發 FULL 模式上傳")
        return preview_path

if __name__ == "__main__":
    main()
