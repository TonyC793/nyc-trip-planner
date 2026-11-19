---
name: nyc-trip
description: Manage the user's 纽约旅行 Notion trip planner (NYC + nearby NJ, 2026-12-12 to 2027-01-11). Use whenever the user sends NYC places, addresses, articles, links, screenshots, brochures or a Google Maps Takeout zip; asks about or plans the itinerary (每日行程 / 每周计划 / 攻略 / 路线); gives feedback on a day they did; reviews 活动推荐; or when the daily NYC events report runs.
---

# 纽约旅行 Notion 助手

The user writes in Chinese — always answer in Chinese, briefly.
Tool: `python3 -I .claude/skills/nyc-trip/scripts/trip.py <cmd>` (run `trip.py` with no args for
the command list). IDs are in `config.json`.

**Before doing anything, read `preferences.md`** (same folder). It holds what the user likes and
what they've told you after past days. It overrides the defaults below.

**Keep it cheap**: no images/covers/maps; emoji only. Navigation = Google Maps links built by the
script. Web search only where this file says. Don't paste JSON or script output into chat.

**Auth**: no token in this repo. The environment's proxy injects the Notion token for
`api.notion.com`; it only sees the「纽约旅行」page. On 401/403 tell the user the session must
run on the Default environment (which holds the Notion secret) and stop.

**Changing this skill**: when the user asks to change how you work (or a preference is clearly
permanent), edit this file / `preferences.md` / the script, then `git commit` and
`git push origin main` in the repo so later sessions get it. Say what you changed.

## Notion structure
- **地点库** (places_db) — one page per place, icon = emoji. Fields: 名称, 类型 (餐馆/咖啡馆/酒吧/
  观景台/景点/博物馆/购物/甜品/演出/节日活动/其他), 区域 (中城 Midtown, 下东区 LES, 东村/西村 Village,
  SoHo/翠贝卡, 熨斗区 Flatiron/NoMad, 下城 Lower Manhattan, 切尔西 Chelsea, 上东区 UES, 上西区 UWS,
  哈莱姆 Harlem, 布朗克斯 Bronx, 布鲁克林 Brooklyn, 皇后区 Queens, 泽西市 Jersey City, 霍博肯 Hoboken, 其他),
  地址, Google Maps链接, 状态 (想去/本周计划/已去/放弃), 计划周次, 优先级 (必去/想去/有空再去),
  最佳时段 (multi), **需要预约** (需要/建议预约/不需要/不接受预约), **预约链接**,
  **排队情况** (不用排/10–30 分钟/30–60 分钟/1 小时以上/看时段), 预算 ($–$$$$), 营业时间备注,
  我的备注, **来源** (article/link it came from), **活动日期** (Notion date; for anything that only
  happens on certain dates — pass `{"start": "2026-12-24"}` or `{"start": …, "end": …}`; put the
  daily time window in 营业时间备注; mark last-year/unconfirmed dates with ⚠️ in 我的备注), 去过后评分.
  The user filters by 区域 and 类型, so always fill both.
- **活动推荐** (recs_db) — daily report items: 名称, 类型, 活动时间 (text), 活动日期 (date range),
  地点, 区域, 链接, 简介, 推荐日期, 决定 (待定/✅ 加入/❌ 不要), 已加入地点库.
- **每周计划**, **每日行程** — weeks 第1周 12/12–13 … 第6周 1/11; one row per date.

## A — add places (the main job until shortly before the trip)

1. Collect every NYC / NJ-waterfront place from what the user sent: Takeout zip
   (`trip.py takeout <zip>`), screenshots, brochures, articles, links, lists. For an article
   link, read the page and take every place it recommends; set 来源 to the link and put the
   article's one-line reason in 我的备注.
2. Fill gaps with at most one quick web search per unclear place. Unconfirmed → empty 地址 and
   `⚠️ 待确认：…` in 我的备注. Never invent addresses or links.
3. Classify: 类型, 区域, specific emoji, 最佳时段, 预算. For 餐馆/酒吧/咖啡馆 always try to fill
   **需要预约** (+ 预约链接 if bookable: Resy/OpenTable/Tock/own site) and **排队情况**; if
   unknown, leave empty — the planning step checks again.
4. `trip.py add places.json` (dupes by Google id, name or address are skipped). Fix rows with
   `trip.py update` (`[{"id": …, <fields>}]`).
   ```json
   [{"名称": "Joe's Pizza", "类型": "餐馆", "区域": "东村/西村 Village", "地址": "7 Carmine St",
     "emoji": "🍕", "最佳时段": ["午餐", "深夜"], "预算": "$", "需要预约": "不接受预约",
     "排队情况": "10–30 分钟", "来源": "https://…", "我的备注": "经典纽约薄底披萨"}]
   ```
5. Reply with counts per 区域/类型, a short table of what was added, skipped dupes, drops, ⚠️ items.

**Do not plan itineraries unless the user asks.** Just collect and classify.

## B — plan days (only when asked, usually close to the trip)

1. `trip.py places`, `trip.py days`, and read `preferences.md`. Candidates: what the user names,
   then anything whose 活动日期 covers that day (fixed-date events first), then 状态 本周计划 / 计划周次, then 必去, then the rest — and ✅ items from 活动推荐 with dates.
2. Look up for the actual date(s) and put on the page: opening hours that day (holidays 12/24,
   12/25, 12/31, 1/1; Mondays), weather (only ≤7 days out, otherwise "出发前一周再查"), sunset
   (mid-Dec ≈16:30, early Jan ≈16:40), and for every restaurant/bar **reservation need + link and
   expected wait at the planned time**. Waits drive the schedule: walk-in-only hot spots go at
   opening time or off-peak; add a backup nearby. Sources + check date go in `notes`.
3. Plan: 1–2 neighbouring 区域 per day; rooftops/观景台 at sunset; ≤6 stops; respect hours;
   legs >~20 min walk → subway (line + stations, `leg.mode: "transit"`).
4. `trip.py day day.json` per day. Spec:
   ```json
   {"date": "2026-12-14", "emoji": "🗽",
    "weather": {"summary": "多云 -1°C / 5°C", "sunset": "16:29"},
    "alert": "今晚 Comedy Cellar 要提前买票",
    "stops": [
      {"place_id": "<id>", "time": "11:30–12:30", "desc": "开门就到，避开排队", "hours": "11:30–22:00",
       "tips": "不接受预约，饭点排队 45 分钟+；备选：隔壁 X",
       "leg": {"mode": "walking", "text": "步行约 8 分钟"}},
      {"place_id": "<id>", "time": "19:45", "desc": "脱口秀", "hours": "19:00 起",
       "booking": {"text": "必须提前买票", "url": "https://…", "label": "官网"},
       "leg": {"mode": "transit", "text": "W 4 St 站坐 F 线到 2 Av 站，约 10 分钟"}},
      {"名称": "Washington Square Park", "地址": "Washington Square", "emoji": "🌳", "time": "18:00"}],
    "fields": {"当天区域": "…", "上午": "…", "下午": "…", "晚上": "…", "餐饮安排": "…",
               "需预约/已预约": "…", "特别提醒": "…"},
    "notes": ["营业时间：<来源>（查询于 …）"]}
   ```
   Add `"example": true` to skip tagging places with 计划周次.
5. Update the week's 每周计划 row; reply with a day-by-day summary, links, and a "现在就要订" list.

## C — learn from feedback

When the user tells you how a day went (in chat or in 每日行程 → 当天感受):
1. Update the places: 状态 → 已去, 去过后评分, and a line in 我的备注.
2. Extract **lasting lessons** (pace, walking tolerance, food taste, queue tolerance, bar style,
   wake-up time, budget, what was overrated …) and add them to `preferences.md` under the right
   heading with the date. Merge, don't duplicate; one line each.
3. Commit + push. Tell the user in one line what you'll do differently.
Always apply `preferences.md` when planning.

## D — daily events report (scheduled run, 19:00 PST)

1. Read `preferences.md`. Web search (keep it to ~6–10 searches) for NYC things relevant to the
   trip window that aren't already in 地点库 or 活动推荐 (`trip.py recs`): new and viral
   openings/articles, seasonal events (holiday markets, light shows, Rockefeller tree, NYE events,
   ice rinks), shows/exhibits, themed bar nights incl. LGBTQ+/gay bars (drag shows, holiday
   parties, NYE), food events. Prefer recent sources (Time Out NY, Secret NYC, Eater NY, The
   Infatuation, Instagram-viral coverage, venue sites).
2. Pick the 5–8 best, each with real dates within 2026-12-12 – 2027-01-11 when possible.
   `trip.py rec-add recs.json` (fields: 名称, emoji, 类型, 活动时间, 活动日期, 地点, 区域, 链接, 简介).
3. Also: rows marked ✅ 加入 with 已加入地点库 unchecked → add to 地点库 (Workflow A; put the
   类型 节日活动 for seasonal events; copy 活动日期; times in 营业时间备注; 链接 → 来源 and, if it
   sells tickets, 预约链接) and tick 已加入地点库 via `trip.py rec-update`. Ignore ❌.
4. Report in Chinese: numbered list (emoji, name, when, where, why, link), then "回复编号即可
   加入地点库，或在 Notion「活动推荐」里把决定改成 ✅ 加入". If the user replies with numbers,
   mark those ✅ and add them.
