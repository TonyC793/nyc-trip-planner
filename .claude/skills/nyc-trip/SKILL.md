---
name: nyc-trip
description: Manage the user's 纽约旅行 Notion trip planner (NYC + nearby NJ, 2026-12-12 to 2027-01-11). Use whenever the user sends places to add — a Google Maps Takeout zip, screenshots of addresses or maps, brochures/flyers/menus, links or plain lists — or asks to plan, adjust or regenerate a day's or week's itinerary (每日行程 / 每周计划 / 攻略 / 路线).
---

# 纽约旅行 Notion 助手

The user writes in Chinese — always answer in Chinese, briefly.
Everything goes through `python3 -I .claude/skills/nyc-trip/scripts/trip.py <cmd>`. IDs are in `config.json`.

**Keep it cheap.** The user explicitly asked to save tokens:
- No preview images, photos, covers or rendered maps. A fitting emoji per place is enough.
- Navigation = Google Maps links (the script builds them). Do not geocode or compute routes.
- Web search only for what the user needs on the day (see Workflow B), not for decoration.
- Don't dump script output or JSON into chat; summarize.

**Auth**: no token in this repo. The cloud environment's proxy injects the Notion connection
token for `api.notion.com`; that connection only sees the「纽约旅行」page. On 401/403, tell the
user the session must run on the environment holding the Notion secret (Default) and stop.

## Notion structure
- **地点库** — one page per place, page icon = emoji. Fields: 名称, 类型 (餐馆/咖啡馆/酒吧/观景台/
  景点/博物馆/购物/甜品/演出/其他), 区域 (中城 Midtown, 下东区 LES, 东村/西村 Village, SoHo/翠贝卡,
  熨斗区 Flatiron/NoMad, 下城 Lower Manhattan, 切尔西 Chelsea, 上东区 UES, 上西区 UWS, 哈莱姆 Harlem,
  布鲁克林 Brooklyn, 皇后区 Queens, 泽西市 Jersey City, 霍博肯 Hoboken, 其他), 地址, Google Maps链接,
  状态 (想去/本周计划/已去/放弃), 计划周次 (第1周…第6周), 优先级 (必去/想去/有空再去),
  最佳时段 (multi: 早上/上午/午餐/下午/日落/晚餐/晚上/深夜), 需要预约 (需要/建议预约/不需要),
  预算 ($–$$$$), 营业时间备注, 我的备注, 去过后评分.
- **每周计划** — 第1周 12/12–13, 第2周 12/14–20, 第3周 12/21–27 (圣诞), 第4周 12/28–1/3 (跨年),
  第5周 1/4–10, 第6周 1/11 (返程).
- **每日行程** — one row per date (title property 星期; 日期, 周次, 当天区域, 上午, 下午, 晚上,
  餐饮安排, 需预约/已预约, 天气, 特别提醒, 当天感受).

## Workflow A — add places

1. Collect candidates:
   - Takeout zip → `trip.py takeout <zip>` (keeps NYC-area entries, flags ones already in Notion).
   - Screenshots / brochures / photos → read them yourself; extract every place name + address.
   - Links / text → parse.
2. Only keep NYC's five boroughs and the NJ waterfront (Jersey City, Hoboken, Weehawken,
   Edgewater, Fort Lee …). If a place's identity or address is unclear, do ONE quick web search;
   still unclear → leave 地址 empty and put `⚠️ 待确认：…` in 我的备注. Never invent an address.
3. Classify: 类型, 区域, a specific `emoji` (🥯 bagel, 🍜 noodles, 🥃 cocktail bar, 📖 bookstore …),
   最佳时段, 需要预约 / 预算 when obvious, a one-line Chinese 我的备注. Keep the user's own notes.
4. Write a JSON list, run `trip.py add places.json`. Duplicates (same Google place id, name or
   address) are skipped. Without a Google Maps链接 the script makes a search link.
   ```json
   [{"名称": "Joe's Pizza", "类型": "餐馆", "区域": "东村/西村 Village", "地址": "7 Carmine St",
     "emoji": "🍕", "最佳时段": ["午餐", "深夜"], "预算": "$", "我的备注": "经典纽约薄底披萨"}]
   ```
   Fix rows with `trip.py update` using `[{"id": "<page id>", <changed fields>}]`.
5. Reply with a short table (emoji, 名称, 类型, 区域) of what was added, plus skipped duplicates,
   out-of-area drops and ⚠️ items to check.

## Workflow B — plan or adjust days

1. `trip.py places` and `trip.py days` for current state. Candidates: 状态 本周计划 or 计划周次 =
   that week, then 必去, then others. The user's request wins.
2. **Look up, for the actual date(s)** — these must appear on the page:
   - each stop's opening hours that day (watch 12/24, 12/25, 12/31, 1/1 and Mondays),
   - weather forecast (temp range + rain/snow) — forecasts are only useful ~7 days out;
     beyond that write "出发前一周再查" instead of guessing,
   - sunset time (NYC mid-Dec ≈ 16:30, early Jan ≈ 16:40; use a source for the exact time),
   - whether booking/tickets are needed, with the official booking URL (Resy/OpenTable/Tock/
     the venue's own site). Never make up a URL; if not found, say "到店排队" or "官网查".
   Put sources + the date you checked into `notes`.
3. Plan: one or two neighbouring 区域 per day; rooftops/观景台 around sunset; meals at meal
   times; indoor stops on bad-weather days; ≤ 6 stops; respect opening hours. Legs over ~20 min
   walking → subway: name the line and stations in `leg.text` and set `leg.mode` to "transit".
4. One JSON per day → `trip.py day day.json`. It replaces that day's page body with a
   weather/sunset callout, Google Maps links for the whole route (walking + transit), and per
   stop: time, emoji + name, opening hours, booking link, tips, and the leg to the next stop with
   its own navigation link. It also fills the day's fields and sets 计划周次 on the places
   (skip that with `"example": true`).
   ```json
   {"date": "2026-12-14", "emoji": "🗽",
    "weather": {"summary": "多云 -1°C / 5°C，无降水", "sunset": "16:29"},
    "alert": "Comedy Cellar 要提前买票",
    "stops": [
      {"place_id": "<地点库 page id>", "time": "14:00–15:00", "desc": "逛书店",
       "hours": "10:00–20:00", "leg": {"mode": "walking", "text": "步行约 8 分钟"}},
      {"place_id": "<id>", "time": "16:00–17:30", "desc": "屋顶看日落", "hours": "12:00–02:00",
       "booking": {"text": "建议订位", "url": "https://…", "label": "官网订位"},
       "leg": {"mode": "transit", "text": "28 St 站坐 R/W 线到 8 St–NYU 站，约 15 分钟"}},
      {"名称": "Washington Square Park", "地址": "Washington Square, New York", "emoji": "🌳",
       "time": "18:00", "desc": "临时加的点", "hours": "全天"}],
    "fields": {"当天区域": "…", "上午": "…", "下午": "…", "晚上": "…", "餐饮安排": "…",
               "需预约/已预约": "…", "特别提醒": "…"},
    "notes": ["营业时间：<来源>（查询于 2026-12-07）"]}
   ```
   Stops not in 地点库 are fine (名称 + 地址); offer to add them to 地点库.
5. After planning a week, update its 每周计划 row (状态, AI攻略已生成 ✓, 本周想去的地点).
6. Reply with a short day-by-day summary + Notion links, and list what must be booked now.

## Rules
- Never put the token or any secret into files, commits or chat.
- Don't delete the user's rows or text; only replace the body of a 每日行程 page being (re)planned.
- When unsure about a place, ask or mark ⚠️ — don't invent.
