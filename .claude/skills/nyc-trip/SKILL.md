---
name: nyc-trip
description: Manage the user's 纽约旅行 Notion trip planner (NYC + nearby NJ, 2026-12-12 to 2027-01-11). Use whenever the user sends places to add — a Google Maps Takeout zip, screenshots of addresses or maps, brochures/flyers/menus, links or plain lists — or asks to plan, adjust or regenerate a day's or week's itinerary (每日行程 / 每周计划 / 攻略 / 路线).
---

# 纽约旅行 Notion 助手

The user (writes in Chinese — always answer in Chinese) keeps a NYC trip planner in Notion.
Everything goes through `scripts/trip.py` (run with `python3 -I`). IDs are in `config.json`.

**Auth**: there is no token in this repo. The cloud environment's network proxy injects the
Notion connection token into requests to `api.notion.com`. That connection can only see the
「纽约旅行」page. If a call returns 401/403, tell the user the session must run on the
environment that holds the Notion secret (their Default environment), and stop.
Map/photo hosts used: nominatim/tile.openstreetmap.org, commons.wikimedia.org,
upload.wikimedia.org. If one is blocked, say so; do not invent data to fill the gap.

## Notion structure
- **地点库** (places_db) — one page per place. Page icon = emoji, page cover = preview image.
  Fields: 名称, 类型 (餐馆/咖啡馆/酒吧/观景台/景点/博物馆/购物/甜品/演出/其他), 区域 (e.g.
  中城 Midtown, 下东区 LES, 东村/西村 Village, SoHo/翠贝卡, 熨斗区 Flatiron/NoMad, 下城 Lower
  Manhattan, 切尔西 Chelsea, 上东区 UES, 上西区 UWS, 哈莱姆 Harlem, 布鲁克林 Brooklyn, 皇后区
  Queens, 泽西市 Jersey City, 霍博肯 Hoboken), 地址, Google Maps链接, 状态 (想去/本周计划/已去/放弃),
  计划周次 (第1周…第6周), 优先级 (必去/想去/有空再去), 最佳时段 (multi), 需要预约, 预算 ($–$$$$),
  营业时间备注, 我的备注, 去过后评分.
- **每周计划** (weeks_db) — 第1周 12/12–12/13, 第2周 12/14–20, 第3周 12/21–27 (圣诞),
  第4周 12/28–1/3 (跨年), 第5周 1/4–10, 第6周 1/11 (返程).
- **每日行程** (days_db) — one row per date; title property is 星期, plus 日期, 周次, 当天区域,
  上午, 下午, 晚上, 餐饮安排, 需预约/已预约, 天气, 特别提醒, 当天感受.

## Workflow A — add places

1. **Collect candidates** from whatever the user sent:
   - Takeout zip → `python3 -I scripts/trip.py takeout <zip>`; it keeps only NYC-area entries
     (Google place id prefix `0x89c2` or coordinates in the NYC box) and flags ones already in Notion.
   - Screenshots / brochures / photos → read them yourself; extract every place name + address.
   - Links / text → parse them.
2. **Fill gaps with web search** (address, what kind of place). Never guess an address; if it
   can't be confirmed, leave 地址 empty and put `⚠️ 待确认：…` in 我的备注.
   Only keep places in NYC's five boroughs or the NJ waterfront (Jersey City, Hoboken, Weehawken,
   Edgewater, Fort Lee …). Mention anything you dropped.
3. **Classify**: 类型, 区域, a fitting specific `emoji` (🥯 bagel, 🍜 noodles, 🥃 cocktail bar,
   📖 bookstore … not just the type default), 最佳时段, 需要预约/预算 if known, a short Chinese
   我的备注 (what it is / why go). Keep the user's own notes from the source.
4. **Cover image**: prefer a freely licensed photo — search Wikimedia Commons near the
   coordinates (`action=query&generator=geosearch&ggsnamespace=6&ggsradius=60&prop=imageinfo
   &iiprop=url|extmetadata&iiurlwidth=1200`, max ~1 request / 2 s, it rate-limits) and pass
   `cover_url` (the 1200px thumburl) + `cover_credit` ("File name, author, license, link").
   No suitable photo → leave `cover_url` out and the script uploads an OpenStreetMap location map.
   Do not hotlink copyrighted photos (Google Maps, Yelp, restaurant sites).
5. Write a JSON list and run `python3 -I scripts/trip.py add places.json`. Example item:
   ```json
   {"名称": "Joe's Pizza", "类型": "餐馆", "区域": "东村/西村 Village", "地址": "7 Carmine St",
    "Google Maps链接": "https://www.google.com/maps/place/...", "emoji": "🍕",
    "最佳时段": ["午餐", "深夜"], "预算": "$", "我的备注": "经典纽约薄底披萨",
    "cover_url": "https://upload.wikimedia.org/...", "cover_credit": "File:… (CC BY-SA 4.0) https://commons.wikimedia.org/wiki/File:…"}
   ```
   Duplicates (same Google place id, same name, or same address) are skipped automatically.
   To fix existing rows: `update` with `[{"id": "<page id>", <fields>, "refresh_map_cover": true}]`.
6. Report in Chinese: a table of what was added (emoji, 名称, 类型, 区域), what was skipped as
   duplicate, what was dropped as out of area, and every ⚠️ item the user should check.

## Workflow B — plan or adjust days

1. `python3 -I scripts/trip.py places` and `days` to see the current state. Candidate places =
   状态 本周计划 / 计划周次 = that week, then 必去, then the rest. Respect what the user asks.
2. **Check live info with web search before scheduling** (this is the point of the workflow):
   opening hours for those exact dates (holidays: 12/24, 12/25, 12/31, 1/1), weather forecast,
   sunset time (~16:30 in mid-Dec), reservation/ticket needs, seasonal events nearby.
   Record sources + the date you checked in `notes`.
3. **Plan**: group by 区域 so each day is walkable; put 观景台/rooftops at sunset; meals at meal
   times; indoor places on bad-weather days; no more than ~6 stops a day; leave slack.
   Use subway for legs over ~25 min walk and say which line in `next_transit`.
4. Write one JSON per day and run `python3 -I scripts/trip.py day day.json`. It replaces that
   day's page body with: route map (cover + inline), Google Maps walking link, per-stop preview
   image + mention of the place page, walk times; fills the day's fields; sets 计划周次 on the places.
   ```json
   {"date": "2026-12-14", "emoji": "🗽",
    "callout": "已于 11/20 核实营业时间和天气（见底部来源）",
    "stops": [
      {"place_id": "<地点库 page id>", "time": "14:00–15:00", "desc": "逛书店"},
      {"place_id": "<id>", "time": "16:00–17:30", "desc": "屋顶看日落", "next_transit": "28 St 站坐 R/W 到 8 St–NYU，约 15 分钟"},
      {"名称": "Washington Square Park", "地址": "Washington Square, New York", "emoji": "🌳", "time": "18:00", "desc": "临时加的点"}],
    "fields": {"当天区域": "熨斗区 → 东村", "上午": "…", "下午": "…", "晚上": "…",
               "餐饮安排": "…", "需预约/已预约": "…", "天气": "…", "特别提醒": "…"},
    "notes": ["营业时间：<来源链接>（查询于 2026-11-20）"]}
   ```
   Stops not in 地点库 are allowed (give 名称 + 地址); ask whether to add them to 地点库 too.
5. When the week is done, also update that week's 每周计划 row (状态, AI攻略已生成 ✓, 本周想去的地点).
6. Reply with a short day-by-day summary + the Notion links the script printed, and list
   anything that needs booking now.

## Rules
- Never put the token or any secret into files, commits or chat.
- Don't delete user rows or text; only replace the body of a 每日行程 page you are (re)planning.
- When unsure about a place's identity or category, ask or mark ⚠️ — don't invent.
