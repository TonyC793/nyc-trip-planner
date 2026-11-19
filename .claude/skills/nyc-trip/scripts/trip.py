#!/usr/bin/env python3
"""NYC trip helper: read/write the 纽约旅行 Notion page.

The Notion token is NOT stored here. The cloud environment's network proxy
injects it into every request to api.notion.com.

Subcommands
  places                       List the 地点库 as JSON.
  takeout ZIP                  Print NYC-area places found in a Google Takeout
                               zip (Saved/*.csv), marking ones already in Notion.
  geocode "ADDRESS or NAME"    Look up coordinates with OpenStreetMap Nominatim.
  add FILE.json                Add places (list of objects, see SKILL.md).
                               Skips duplicates; adds emoji + cover.
  update FILE.json             Patch existing places: [{"id":..., <fields>}].
  day FILE.json                Write one day's itinerary (route map, timeline).
  days                         List 每日行程 rows (date, id, filled or not).
"""
import csv, io, json, math, os, re, sys, time, unicodedata, urllib.parse, urllib.request, uuid, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "..", "config.json")))
H = {"Notion-Version": CFG["notion_version"]}
UA = {"User-Agent": "personal-trip-planner/1.0 (personal use)"}
WORK = os.environ.get("TRIP_WORKDIR", "/tmp/nyc-trip")
os.makedirs(WORK + "/tiles", exist_ok=True)

TYPE_EMOJI = {"餐馆": "🍽️", "咖啡馆": "☕", "酒吧": "🍸", "观景台": "🌆", "景点": "🏛️", "博物馆": "🖼️",
              "购物": "🛍️", "甜品": "🍰", "演出": "🎭", "其他": "📍"}
FIELDS_SELECT = ["类型", "区域", "状态", "计划周次", "优先级", "需要预约", "预算", "去过后评分"]
FIELDS_TEXT = ["地址", "营业时间备注", "我的备注"]

# ---------------- Notion ----------------
def api(method, path, body=None):
    req = urllib.request.Request("https://api.notion.com/v1/" + path,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={**H, "Content-Type": "application/json"}, method=method)
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

def upload_png(path):
    name = os.path.basename(path)
    fu = api("POST", "file_uploads", {"mode": "single_part", "filename": name, "content_type": "image/png"})
    b = "----" + uuid.uuid4().hex
    body = (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            f"Content-Type: image/png\r\n\r\n").encode() + open(path, "rb").read() + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(f"https://api.notion.com/v1/file_uploads/{fu['id']}/send", data=body,
                                 headers={**H, "Content-Type": f"multipart/form-data; boundary={b}"}, method="POST")
    d = json.load(urllib.request.urlopen(req, timeout=120))
    assert d["status"] == "uploaded", d
    return fu["id"]

def txt(p):
    t = p.get("type")
    if t == "title": return "".join(x["plain_text"] for x in p["title"])
    if t == "rich_text": return "".join(x["plain_text"] for x in p["rich_text"])
    if t == "select": return (p["select"] or {}).get("name")
    if t == "multi_select": return [x["name"] for x in p["multi_select"]]
    if t == "url": return p["url"]
    if t == "date": return (p["date"] or {}).get("start")
    if t == "checkbox": return p["checkbox"]
    return None

def place_rows():
    rows = []
    for r in query_all(CFG["places_db"]):
        d = {k: txt(v) for k, v in r["properties"].items()}
        d["id"] = r["id"]; d["emoji"] = (r.get("icon") or {}).get("emoji")
        d["has_cover"] = bool(r.get("cover"))
        rows.append(d)
    return rows

# ---------------- dedupe helpers ----------------
def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"（.*?）|\(.*?\)", "", s)
    return re.sub(r"[^a-z0-9]", "", s)

def cid(url):
    m = re.search(r"(0x[0-9a-f]+:0x[0-9a-f]+)", url or "")
    return m.group(1) if m else None

def find_dupe(p, rows):
    c = cid(p.get("Google Maps链接"))
    for r in rows:
        if c and c == cid(r.get("Google Maps链接")): return r
        if norm(p["名称"]) and norm(p["名称"]) == norm(r.get("名称")): return r
        a1, a2 = norm(p.get("地址")), norm(r.get("地址"))
        if a1 and a1 == a2: return r
        if a2 and norm(p["名称"]) == a2: return r  # a "place" that is just an address
    return None

# ---------------- geo ----------------
def geocode(q):
    u = "https://nominatim.openstreetmap.org/search?format=json&limit=1&q=" + urllib.parse.quote(q)
    r = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30))
    time.sleep(1.1)  # Nominatim policy: max 1 req/s
    return (float(r[0]["lat"]), float(r[0]["lon"]), r[0]["display_name"]) if r else None

def _px(lat, lon, z):
    n = 256 * 2 ** z
    return ((lon + 180) / 360 * n,
            (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)

def _tile(z, x, y):
    from PIL import Image
    f = f"{WORK}/tiles/{z}_{x}_{y}.png"
    if not os.path.exists(f):
        d = urllib.request.urlopen(urllib.request.Request(
            f"https://tile.openstreetmap.org/{z}/{x}/{y}.png", headers=UA), timeout=30).read()
        open(f, "wb").write(d); time.sleep(0.2)
    return Image.open(f).convert("RGB")

def render_map(points, out, W=1200, H=500, zmax=17, route=False, pad=90):
    from PIL import Image, ImageDraw, ImageFont
    def font(s):
        p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        return ImageFont.truetype(p, s) if os.path.exists(p) else ImageFont.load_default()
    for z in range(zmax, 10, -1):
        xs, ys = zip(*[_px(a, b, z) for a, b in points])
        if max(xs) - min(xs) <= W - 2 * pad and max(ys) - min(ys) <= H - 2 * pad: break
    x0 = (max(xs) + min(xs)) / 2 - W / 2; y0 = (max(ys) + min(ys)) / 2 - H / 2
    img = Image.new("RGB", (W, H))
    for tx in range(int(x0 // 256), int((x0 + W) // 256) + 1):
        for ty in range(int(y0 // 256), int((y0 + H) // 256) + 1):
            img.paste(_tile(z, tx, ty), (int(tx * 256 - x0), int(ty * 256 - y0)))
    d = ImageDraw.Draw(img, "RGBA")
    P = [(x - x0, y - y0) for x, y in zip(xs, ys)]
    if route:
        for i in range(len(P) - 1): d.line([P[i], P[i + 1]], fill=(220, 38, 38, 230), width=7)
    for i, (x, y) in enumerate(P):
        r = 22 if route else 18
        d.ellipse([x - r, y - r, x + r, y + r], fill=(220, 38, 38, 255), outline="white", width=4)
        if route:
            f = font(22); t = str(i + 1); d.text((x - d.textlength(t, font=f) / 2, y - 13), t, fill="white", font=f)
    f = font(15); t = "© OpenStreetMap contributors"; w = d.textlength(t, font=f)
    d.rectangle([W - w - 16, H - 26, W, H], fill=(255, 255, 255, 200)); d.text((W - w - 8, H - 23), t, fill=(60, 60, 60), font=f)
    img.save(out); return out

def walk_minutes(a, b):
    R = 6371000; la1, lo1, la2, lo2 = map(math.radians, [*a, *b])
    d = 2 * R * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2 +
                                    math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)) * 1.3
    return d, max(1, round(d / 80))

def coords_for(p):
    for q in [p.get("地址") and f"{p['地址']}, New York", p.get("名称") and f"{p['名称']}, New York"]:
        if q:
            g = geocode(q)
            if g: return g
    return None

# ---------------- commands ----------------
def rt(s): return {"rich_text": [{"text": {"content": s}}] if s else []}

def props_from(p):
    out = {}
    if "名称" in p: out["名称"] = {"title": [{"text": {"content": p["名称"]}}]}
    for k in FIELDS_SELECT:
        if p.get(k): out[k] = {"select": {"name": p[k]}}
    for k in FIELDS_TEXT:
        if k in p: out[k] = rt(p[k] or "")
    if p.get("Google Maps链接"): out["Google Maps链接"] = {"url": p["Google Maps链接"]}
    if "最佳时段" in p: out["最佳时段"] = {"multi_select": [{"name": x} for x in p["最佳时段"]]}
    return out

def ensure_options(places):
    """Add any new select values (e.g. a new 类型 or 区域) to the schema first."""
    db = api("GET", f"databases/{CFG['places_db']}")
    patch = {}
    for k in FIELDS_SELECT:
        have = {o["name"] for o in db["properties"][k]["select"]["options"]}
        new = sorted({p[k] for p in places if p.get(k) and p[k] not in have})
        if new: patch[k] = {"select": {"options": [{"name": n} for n in new]}}
    if patch: api("PATCH", f"databases/{CFG['places_db']}", {"properties": patch})

def set_cover(page_id, p, latlon):
    if p.get("cover_url"):
        api("PATCH", f"pages/{page_id}", {"cover": {"type": "external", "external": {"url": p["cover_url"]}}})
        if p.get("cover_credit"):
            api("PATCH", f"blocks/{page_id}/children", {"children": [{"object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": "📷 封面：" + p["cover_credit"]},
                                             "annotations": {"color": "gray"}}]}}]})
    elif latlon:
        f = render_map([latlon], f"{WORK}/cover_{page_id}.png")
        api("PATCH", f"pages/{page_id}", {"cover": {"type": "file_upload", "file_upload": {"id": upload_png(f)}}})

def cmd_add(path):
    places = json.load(open(path)); rows = place_rows(); ensure_options(places)
    for p in places:
        d = find_dupe(p, rows)
        if d:
            print(json.dumps({"skipped_duplicate": p["名称"], "existing": d["名称"], "id": d["id"]}, ensure_ascii=False)); continue
        p.setdefault("状态", "想去")
        g = coords_for(p)
        page = api("POST", "pages", {"parent": {"database_id": CFG["places_db"]},
                                      "icon": {"type": "emoji", "emoji": p.get("emoji") or TYPE_EMOJI.get(p.get("类型"), "📍")},
                                      "properties": props_from(p)})
        set_cover(page["id"], p, g[:2] if g else None)
        rows.append({"id": page["id"], **p})
        print(json.dumps({"added": p["名称"], "id": page["id"], "geocoded": g[2][:80] if g else None}, ensure_ascii=False))

def cmd_update(path):
    for p in json.load(open(path)):
        ensure_options([p])
        body = {"properties": props_from(p)}
        if p.get("emoji"): body["icon"] = {"type": "emoji", "emoji": p["emoji"]}
        api("PATCH", f"pages/{p['id']}", body)
        if p.get("cover_url") or p.get("refresh_map_cover"):
            g = None if p.get("cover_url") else coords_for(p)
            set_cover(p["id"], p, g[:2] if g else None)
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
                key = c or url
                e = found.setdefault(key, {"名称": r.get("Title") or "", "Google Maps链接": url, "lists": [], "note": r.get("Note") or ""})
                e["lists"].append(lst)
    for e in found.values():
        d = find_dupe(e, rows)
        e["already_in_notion"] = d["名称"] if d else None
    print(json.dumps(list(found.values()), ensure_ascii=False, indent=1))

def cmd_days():
    for r in sorted(query_all(CFG["days_db"]), key=lambda r: txt(r["properties"]["日期"]) or ""):
        p = r["properties"]
        print(txt(p["日期"]), txt(p["星期"]), txt(p["周次"]), r["id"], "已排" if txt(p["下午"]) or txt(p["晚上"]) else "空")

def cmd_day(path):
    spec = json.load(open(path))
    rows = {r["id"]: r for r in place_rows()}
    day = query_all(CFG["days_db"], {"filter": {"property": "日期", "date": {"equals": spec["date"]}}})
    if not day: sys.exit("no 每日行程 row for " + spec["date"])
    did = day[0]["id"]
    # clear old body
    for b in api("GET", f"blocks/{did}/children?page_size=100")["results"]:
        api("DELETE", f"blocks/{b['id']}")
    stops = spec["stops"]
    pts, addrs = [], []
    for s in stops:
        r = rows.get(s.get("place_id"), {})
        s.setdefault("名称", r.get("名称")); s.setdefault("地址", r.get("地址")); s.setdefault("emoji", r.get("emoji") or "📍")
        g = coords_for(s); pts.append(g[:2] if g else None)
        addrs.append((s.get("地址") or s["名称"]) + ", New York, NY")
    ok = [p for p in pts if p]
    T = lambda s, link=None, **ann: {"type": "text", "text": {"content": s, **({"link": {"url": link}} if link else {})},
                                     **({"annotations": ann} if ann else {})}
    P = lambda *x: {"object": "block", "type": "paragraph", "paragraph": {"rich_text": list(x)}}
    gm = "https://www.google.com/maps/dir/?api=1&" + urllib.parse.urlencode({
        "origin": addrs[0], "destination": addrs[-1], "waypoints": "|".join(addrs[1:-1]), "travelmode": "walking"})
    blocks = []
    if spec.get("callout"):
        blocks.append({"object": "block", "type": "callout", "callout": {"icon": {"type": "emoji", "emoji": "💡"},
                       "color": "yellow_background", "rich_text": [T(spec["callout"])]}})
    route_id = None
    if len(ok) >= 2:
        f = render_map(ok, f"{WORK}/route_{spec['date']}.png", H=800, zmax=16, route=True)
        route_id = upload_png(f)
        blocks += [{"object": "block", "type": "heading_2", "heading_2": {"rich_text": [T("🗺️ 当天路线")]}},
                   {"object": "block", "type": "image", "image": {"type": "file_upload", "file_upload": {"id": route_id},
                    "caption": [T("红线是站点之间的直线示意，不是实际步行路线。数字是游览顺序。")]}}]
    blocks += [P(T("👉 在 Google 地图打开完整步行路线", gm, bold=True)),
               {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [T("⏱️ 时间线")]}}]
    circ = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫"
    for i, s in enumerate(stops):
        blocks.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": [
            T(f"{circ[i]} {s.get('time', '')}  {s['emoji']} {s['名称']}")]}})
        r = rows.get(s.get("place_id"))
        cover = None
        if r:
            pg = api("GET", f"pages/{r['id']}")
            if (pg.get("cover") or {}).get("type") == "external": cover = pg["cover"]["external"]["url"]
        if cover:
            blocks.append({"object": "block", "type": "image", "image": {"type": "external", "external": {"url": cover}}})
        elif pts[i]:
            f = render_map([pts[i]], f"{WORK}/stop_{spec['date']}_{i}.png", H=450)
            blocks.append({"object": "block", "type": "image", "image": {"type": "file_upload", "file_upload": {"id": upload_png(f)}}})
        line = [T(s.get("desc", ""))]
        if r: line += [T("　·　"), {"type": "mention", "mention": {"type": "page", "page": {"id": r["id"]}}}]
        blocks.append(P(*line))
        if i < len(stops) - 1:
            if s.get("next_transit"):
                blocks.append(P(T("🚇 " + s["next_transit"], color="gray", italic=True)))
            elif pts[i] and pts[i + 1]:
                d, m = walk_minutes(pts[i], pts[i + 1])
                blocks.append(P(T(f"🚶 步行约 {m} 分钟（约 {d/1000:.1f} km）", color="gray", italic=True)))
    if spec.get("notes"):
        blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [T("📝 备注与来源")]}})
        blocks += [P(T(n)) for n in spec["notes"]]
    for i in range(0, len(blocks), 90):
        api("PATCH", f"blocks/{did}/children", {"children": blocks[i:i + 90]})
    fields = {k: rt(v) for k, v in spec.get("fields", {}).items()}
    body = {"properties": fields, "icon": {"type": "emoji", "emoji": spec.get("emoji", "🗽")}}
    if route_id:
        body["cover"] = {"type": "file_upload", "file_upload": {"id": upload_png(f"{WORK}/route_{spec['date']}.png")}}
    api("PATCH", f"pages/{did}", body)
    # mark places as planned for that week
    week = txt(day[0]["properties"]["周次"])
    for s in stops:
        if s.get("place_id") and week:
            api("PATCH", f"pages/{s['place_id']}", {"properties": {"计划周次": {"select": {"name": week}}}})
    print(json.dumps({"day_page": did, "url": "https://www.notion.so/" + did.replace("-", ""), "stops": len(stops)}, ensure_ascii=False))

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: sys.exit(__doc__)
    c = a[0]
    if c == "places": print(json.dumps(place_rows(), ensure_ascii=False, indent=1))
    elif c == "takeout": cmd_takeout(a[1])
    elif c == "geocode": print(geocode(a[1]))
    elif c == "add": cmd_add(a[1])
    elif c == "update": cmd_update(a[1])
    elif c == "day": cmd_day(a[1])
    elif c == "days": cmd_days()
    else: sys.exit(__doc__)
