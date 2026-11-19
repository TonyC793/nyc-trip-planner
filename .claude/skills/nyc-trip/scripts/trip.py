#!/usr/bin/env python3
"""NYC trip helper: read/write the 纽约旅行 Notion page.

The Notion token is NOT stored here. The cloud environment's network proxy
injects it into every request to api.notion.com.

Subcommands
  places            List the 地点库 as compact JSON.
  takeout ZIP       NYC-area places in a Google Takeout zip (Saved/*.csv),
                    each marked with the Notion row it duplicates, if any.
  add FILE.json     Add places (list of objects, see SKILL.md); skips duplicates.
  update FILE.json  Patch existing places: [{"id": ..., <fields>}].
  days              List 每日行程 rows (date, weekday, week, id, filled?).
  day FILE.json     Write one day's itinerary page (see SKILL.md).
"""
import csv, io, json, os, re, sys, time, unicodedata, urllib.parse, urllib.request, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "..", "config.json")))
H = {"Notion-Version": CFG["notion_version"], "Content-Type": "application/json"}

TYPE_EMOJI = {"餐馆": "🍽️", "咖啡馆": "☕", "酒吧": "🍸", "观景台": "🌆", "景点": "🏛️", "博物馆": "🖼️",
              "购物": "🛍️", "甜品": "🍰", "演出": "🎭", "其他": "📍"}
FIELDS_SELECT = ["类型", "区域", "状态", "计划周次", "优先级", "需要预约", "预算", "去过后评分"]
FIELDS_TEXT = ["地址", "营业时间备注", "我的备注"]

# ---------------- Notion ----------------
def api(method, path, body=None):
    req = urllib.request.Request("https://api.notion.com/v1/" + path,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers=H, method=method)
    for i in range(4):
        try:
            return json.load(urllib.request.urlopen(req, timeout=60))
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and i < 3:
                time.sleep(2 * (i + 1)); continue
            sys.exit(f"Notion API {e.code}: {e.read()[:500]!r}")

def query_all(db, body=None):
    out, cur = [], None
    while True:
        b = dict(body or {}); b["page_size"] = 100
        if cur: b["start_cursor"] = cur
        d = api("POST", f"databases/{db}/query", b)
        out += d["results"]
        if not d.get("has_more"): return out
        cur = d["next_cursor"]

def txt(p):
    t = p.get("type")
    if t == "title": return "".join(x["plain_text"] for x in p["title"])
    if t == "rich_text": return "".join(x["plain_text"] for x in p["rich_text"])
    if t == "select": return (p["select"] or {}).get("name")
    if t == "multi_select": return [x["name"] for x in p["multi_select"]]
    if t in ("url", "checkbox"): return p[t]
    if t == "date": return (p["date"] or {}).get("start")
    return None

def place_rows():
    rows = []
    for r in query_all(CFG["places_db"]):
        d = {k: v for k, v in ((k, txt(v)) for k, v in r["properties"].items()) if v not in (None, "", [])}
        d["id"] = r["id"]; d["emoji"] = (r.get("icon") or {}).get("emoji")
        rows.append(d)
    return rows

# ---------------- dedupe ----------------
def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"（.*?）|\(.*?\)", "", s)
    return re.sub(r"[^a-z0-9]", "", s)

def cid(url):
    m = re.search(r"(0x[0-9a-f]+:0x[0-9a-f]+)", url or "")
    return m.group(1) if m else None

def find_dupe(p, rows):
    c = cid(p.get("Google Maps链接"))
    n = norm(p.get("名称"))
    for r in rows:
        a = norm(r.get("地址"))
        if c and c == cid(r.get("Google Maps链接")): return r
        if n and n == norm(r.get("名称")): return r
        if a and (a == norm(p.get("地址")) or a == n): return r
    return None

# ---------------- places ----------------
def rt(s): return {"rich_text": [{"text": {"content": s}}] if s else []}

def props_from(p):
    out = {}
    if "名称" in p: out["名称"] = {"title": [{"text": {"content": p["名称"]}}]}
    for k in FIELDS_SELECT:
        if k in p: out[k] = {"select": {"name": p[k]} if p[k] else None}
    for k in FIELDS_TEXT:
        if k in p: out[k] = rt(p[k] or "")
    if "Google Maps链接" in p: out["Google Maps链接"] = {"url": p["Google Maps链接"] or None}
    if "最佳时段" in p: out["最佳时段"] = {"multi_select": [{"name": x} for x in p["最佳时段"]]}
    return out

def ensure_options(places):
    """Add new select values (e.g. a new 类型 or 区域) to the schema first."""
    db = api("GET", f"databases/{CFG['places_db']}")
    patch = {}
    for k in FIELDS_SELECT:
        have = {o["name"] for o in db["properties"][k]["select"]["options"]}
        new = sorted({p[k] for p in places if p.get(k) and p[k] not in have})
        if new: patch[k] = {"select": {"options": [{"name": n} for n in new]}}
    if patch: api("PATCH", f"databases/{CFG['places_db']}", {"properties": patch})

def maps_link(p):
    q = ", ".join(x for x in [p.get("名称"), p.get("地址"), "New York"] if x)
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(q)

def cmd_add(path):
    places = json.load(open(path)); rows = place_rows(); ensure_options(places)
    for p in places:
        d = find_dupe(p, rows)
        if d:
            print(json.dumps({"skipped_duplicate": p["名称"], "existing": d["名称"], "id": d["id"]}, ensure_ascii=False)); continue
        p.setdefault("状态", "想去")
        p.setdefault("Google Maps链接", maps_link(p))
        page = api("POST", "pages", {"parent": {"database_id": CFG["places_db"]},
                                      "icon": {"type": "emoji", "emoji": p.get("emoji") or TYPE_EMOJI.get(p.get("类型"), "📍")},
                                      "properties": props_from(p)})
        rows.append({"id": page["id"], **p})
        print(json.dumps({"added": p["名称"], "id": page["id"]}, ensure_ascii=False))

def cmd_update(path):
    items = json.load(open(path)); ensure_options(items)
    for p in items:
        body = {"properties": props_from(p)}
        if p.get("emoji"): body["icon"] = {"type": "emoji", "emoji": p["emoji"]}
        api("PATCH", f"pages/{p['id']}", body)
        print("updated", p["id"])

def cmd_takeout(zpath):
    rows = place_rows(); found = {}
    with zipfile.ZipFile(zpath) as z:
        for n in z.namelist():
            if "/Saved/" not in n or not n.endswith(".csv"): continue
            lst = os.path.splitext(os.path.basename(n))[0]
            for r in csv.DictReader(io.TextIOWrapper(z.open(n), encoding="utf-8-sig")):
                url = r.get("URL") or ""
                c = cid(url)
                m = re.search(r"/maps/search/(-?[\d.]+),(-?[\d.]+)", url)
                near_nyc = (c and c.startswith("0x89c2")) or (
                    m and 40.45 < float(m.group(1)) < 41.0 and -74.3 < float(m.group(2)) < -73.65)
                if not near_nyc: continue
                e = found.setdefault(c or url, {"名称": r.get("Title") or "", "Google Maps链接": url, "lists": [], "note": r.get("Note") or ""})
                e["lists"].append(lst)
    for e in found.values():
        d = find_dupe(e, rows)
        e["already_in_notion"] = d["名称"] if d else None
    print(json.dumps(list(found.values()), ensure_ascii=False, indent=1))

# ---------------- days ----------------
def cmd_days():
    for r in sorted(query_all(CFG["days_db"]), key=lambda r: txt(r["properties"]["日期"]) or ""):
        p = r["properties"]
        print(txt(p["日期"]), txt(p["星期"]), txt(p["周次"]), r["id"], "已排" if txt(p["下午"]) or txt(p["晚上"]) else "空")

def dir_link(addrs, mode):
    q = {"origin": addrs[0], "destination": addrs[-1], "travelmode": mode}
    if len(addrs) > 2: q["waypoints"] = "|".join(addrs[1:-1])
    return "https://www.google.com/maps/dir/?api=1&" + urllib.parse.urlencode(q)

def cmd_day(path):
    spec = json.load(open(path))
    rows = {r["id"]: r for r in place_rows()}
    day = query_all(CFG["days_db"], {"filter": {"property": "日期", "date": {"equals": spec["date"]}}})
    if not day: sys.exit("no 每日行程 row for " + spec["date"])
    did = day[0]["id"]
    for b in api("GET", f"blocks/{did}/children?page_size=100")["results"]:
        api("DELETE", f"blocks/{b['id']}")

    T = lambda s, link=None, **ann: {"type": "text", "text": {"content": s, **({"link": {"url": link}} if link else {})},
                                     **({"annotations": ann} if ann else {})}
    P = lambda *x: {"object": "block", "type": "paragraph", "paragraph": {"rich_text": list(x)}}
    H2 = lambda s: {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [T(s)]}}
    H3 = lambda s: {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [T(s)]}}
    BUL = lambda *x: {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": list(x)}}

    stops = spec["stops"]
    for s in stops:
        r = rows.get(s.get("place_id"), {})
        s.setdefault("名称", r.get("名称")); s.setdefault("地址", r.get("地址")); s.setdefault("emoji", r.get("emoji") or "📍")
        s["_addr"] = ", ".join(x for x in [s["名称"], s.get("地址"), "New York, NY"] if x)
    addrs = [s["_addr"] for s in stops]

    w = spec.get("weather", {})
    head = [f"🌤️ 天气：{w['summary']}" if w.get("summary") else None,
            f"🌇 日落：{w['sunset']}" if w.get("sunset") else None]
    blocks = [{"object": "block", "type": "callout", "callout": {"icon": {"type": "emoji", "emoji": "📌"},
               "color": "blue_background", "rich_text": [T("　".join(x for x in head if x) or "天气 / 日落待补充")]}}]
    if spec.get("alert"):
        blocks.append({"object": "block", "type": "callout", "callout": {"icon": {"type": "emoji", "emoji": "⚠️"},
                       "color": "yellow_background", "rich_text": [T(spec["alert"])]}})
    blocks.append(P(T("🗺️ 全天路线（Google 地图步行导航）", dir_link(addrs, "walking"), bold=True)))
    if len(stops) > 1:
        blocks.append(P(T("🚇 同一路线的公共交通导航", dir_link(addrs, "transit"), color="gray")))

    blocks.append(H2("⏱️ 时间线"))
    circ = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫"
    for i, s in enumerate(stops):
        blocks.append(H3(f"{circ[i]} {s.get('time', '')}  {s['emoji']} {s['名称']}"))
        line = [T(s.get("desc", ""))]
        if s.get("place_id") in rows:
            line += [T("　·　"), {"type": "mention", "mention": {"type": "page", "page": {"id": s["place_id"]}}}]
        blocks.append(P(*line))
        blocks.append(BUL(T("🕒 营业时间："), T(s.get("hours") or "⚠️ 未查到，去之前确认", bold=bool(s.get("hours")))))
        if s.get("booking"):
            b = s["booking"]
            blocks.append(BUL(T("🎟️ " + b.get("text", "需要预约") + "："), T(b.get("label", "预约链接"), b.get("url"))))
        if s.get("tips"):
            blocks.append(BUL(T("💡 " + s["tips"])))
        if i < len(stops) - 1:
            leg = s.get("leg") or {}
            mode = leg.get("mode", "walking")
            icon = {"walking": "🚶", "transit": "🚇"}.get(mode, "🚕")
            blocks.append(P(T(f"{icon} {leg.get('text', '前往下一站')}　", color="gray", italic=True),
                            T("导航", dir_link([addrs[i], addrs[i + 1]], mode if mode in ("walking", "transit") else "driving"), color="gray")))

    bookings = [s for s in stops if s.get("booking")]
    if bookings:
        blocks.append(H2("🎟️ 需要预约 / 买票"))
        blocks += [BUL(T(f"{s['emoji']} {s['名称']}：{s['booking'].get('text', '需要预约')} "),
                       T(s["booking"].get("label", "预约链接"), s["booking"].get("url"))) for s in bookings]
    if spec.get("notes"):
        blocks.append(H2("📝 备注与来源"))
        blocks += [BUL(T(n)) for n in spec["notes"]]
    for i in range(0, len(blocks), 90):
        api("PATCH", f"blocks/{did}/children", {"children": blocks[i:i + 90]})

    fields = dict(spec.get("fields", {}))
    if w and "天气" not in fields:
        fields["天气"] = "　".join(x for x in [w.get("summary"), w.get("sunset") and "日落 " + w["sunset"]] if x)
    api("PATCH", f"pages/{did}", {"properties": {k: rt(v) for k, v in fields.items()},
                                   "icon": {"type": "emoji", "emoji": spec.get("emoji", "🗽")}})
    if not spec.get("example"):
        week = txt(day[0]["properties"]["周次"])
        for s in stops:
            if s.get("place_id") in rows and week:
                api("PATCH", f"pages/{s['place_id']}", {"properties": {"计划周次": {"select": {"name": week}}}})
    print(json.dumps({"day_page": did, "url": "https://www.notion.so/" + did.replace("-", ""), "stops": len(stops)}, ensure_ascii=False))

if __name__ == "__main__":
    a = sys.argv[1:]
    cmds = {"places": lambda: print(json.dumps(place_rows(), ensure_ascii=False)),
            "takeout": lambda: cmd_takeout(a[1]), "add": lambda: cmd_add(a[1]), "update": lambda: cmd_update(a[1]),
            "days": cmd_days, "day": lambda: cmd_day(a[1])}
    if not a or a[0] not in cmds: sys.exit(__doc__)
    cmds[a[0]]()
