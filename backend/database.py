"""China Travel Map - Database Module"""
import sqlite3, os, math
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "china_travel.db")
def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS attractions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, rating TEXT, city TEXT, province TEXT,
            address TEXT, lat REAL, lng REAL, description TEXT,
            recommend TEXT, source TEXT, phone TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS foods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, city TEXT, province TEXT,
            lat REAL, lng REAL, description TEXT,
            address TEXT, shop_name TEXT, recommend_dish TEXT,
            phone TEXT, source TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_att_rating ON attractions(rating);
        CREATE INDEX IF NOT EXISTS idx_att_province ON attractions(province);
        CREATE INDEX IF NOT EXISTS idx_food_city ON foods(city);
        CREATE INDEX IF NOT EXISTS idx_att_lat_lng ON attractions(lat, lng);
        CREATE INDEX IF NOT EXISTS idx_food_lat_lng ON foods(lat, lng);
    """)
    # idempotent migrations for older DBs missing columns added later
    for tbl in ("attractions", "foods"):
        cols = {row[1] for row in conn.execute("PRAGMA table_info(" + tbl + ")").fetchall()}
        if "phone" not in cols:
            conn.execute("ALTER TABLE " + tbl + " ADD COLUMN phone TEXT")
    conn.commit()
    conn.close()
def haversine(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# Rating priority for picking the "best" record when merging duplicates
_RATING_PRIORITY = {
    "5A": 0, "世界遗产": 0,
    "4A": 1, "国家级旅游度假区": 1,
    "3A": 2, "国家级旅游休闲街区": 2,
    "2A": 3, "滑雪": 3,
    "": 4,
}

def _normalize_name(name):
    """Normalize attraction/food name for deduplication.

    Strips parenthetical content (e.g., "（暂停开放）") and trailing
    qualifiers so e.g. "颐和园" and "颐和园景区" collapse together.
    """
    if not name:
        return ""
    import re
    s = str(name).strip()
    # Drop parenthetical/bracket content
    s = re.sub(r"[（(][^）)]*[）)]", "", s).strip()
    # Drop common trailing suffix words
    for suffix in ["旅游景区", "景区", "风景区", "游览区", "文化旅游区", "旅游区", "风景名胜区"]:
        if s.endswith(suffix) and len(s) > len(suffix) + 2:
            s = s[: -len(suffix)]
            break
    return s

def _dedup_attractions(items):
    """Merge attraction records that represent the same physical place.

    Within the same city, two records are merged if:
      - Their normalized names are equal, OR
      - They are within ~300m of each other AND share a 4+ char substring
    The merged record keeps the highest-priority rating, the most-detailed
    description, and merges sources/phones.
    """
    if not items:
        return items
    parent = list(range(len(items)))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    norms = [_normalize_name(i.get("name", "")) for i in items]
    n = len(items)
    for idx in range(n):
        nm = norms[idx]
        if not nm:
            continue
        city = (items[idx].get("city") or "").strip()
        lat = items[idx].get("lat") or 0
        lng = items[idx].get("lng") or 0
        for j in range(idx + 1, n):
            if find(idx) == find(j):
                continue
            other = items[j]
            o_city = (other.get("city") or "").strip()
            o_lat = other.get("lat") or 0
            o_lng = other.get("lng") or 0
            if city and o_city and city != o_city:
                continue
            # Same normalized name => definite duplicate
            if norms[j] and norms[j] == nm:
                union(idx, j)
                continue
            # Within 300m AND names are related => likely same place
            if lat and lng and o_lat and o_lng:
                d = haversine(lat, lng, o_lat, o_lng)
                if d < 0.3:
                    shorter, longer = (nm, norms[j]) if len(nm) <= len(norms[j]) else (norms[j], nm)
                    if not shorter:
                        continue
                    # Case 1: shorter name is fully contained in longer (>=2 chars)
                    # e.g., "颐和园" in "北京皇家园林—颐和园"
                    if len(shorter) >= 2 and shorter in longer:
                        union(idx, j)
                        continue
                    # Case 2: share a 3+ char common substring
                    if len(shorter) >= 3:
                        for start in range(0, len(shorter) - 2):
                            sub = shorter[start:start + 3]
                            if sub in longer:
                                union(idx, j)
                                break
                    # Case 3: coordinates essentially identical (<10m) - same place
                    # regardless of name (catches data-entry errors with same coords
                    # but different name strings)
                    if d < 0.01:
                        union(idx, j)

    # Build merged records
    clusters = {}
    for idx in range(n):
        r = find(idx)
        clusters.setdefault(r, []).append(idx)

    merged = []
    for cluster_indices in clusters.values():
        if len(cluster_indices) == 1:
            merged.append(dict(items[cluster_indices[0]]))
            continue
        cluster = [items[i] for i in cluster_indices]
        # Pick representative: highest rating priority, then most-complete fields
        cluster.sort(key=lambda x: (
            _RATING_PRIORITY.get(x.get("rating") or "", 9),
            -len(x.get("description") or ""),
            -len(x.get("address") or ""),
        ))
        rep = dict(cluster[0])
        # Merge sources
        sources = sorted({(c.get("source") or "").strip() for c in cluster if c.get("source")})
        rep["source"] = "+".join(s for s in sources if s)
        # Merge phone: prefer first non-empty
        if not rep.get("phone"):
            for c in cluster:
                if c.get("phone"):
                    rep["phone"] = c["phone"]
                    break
        # Tag with merge count for transparency
        rep["merged_count"] = len(cluster)
        alts = sorted({(c.get("name") or "").strip() for c in cluster})
        rep["alt_names"] = [a for a in alts if a and a != rep.get("name")]
        merged.append(rep)
    return merged

def _dedup_foods(items):
    """Merge food records that look like the same shop / chain in same city.

    Key: (city, normalized shop_name or name).
    """
    if not items:
        return items
    by_key = {}
    for it in items:
        shop = (it.get("shop_name") or "").strip()
        name = (it.get("name") or "").strip()
        key_name = _normalize_name(shop or name)
        key = ((it.get("city") or "").strip(), key_name or (shop or name))
        if key not in by_key:
            by_key[key] = dict(it)
            continue
        existing = by_key[key]
        # Pick the more complete record; merge missing fields
        score_new = sum(1 for v in it.values() if v)
        score_existing = sum(1 for v in existing.values() if v)
        if score_new > score_existing:
            merged = dict(it)
            for k, v in existing.items():
                if v and not merged.get(k):
                    merged[k] = v
            by_key[key] = merged
        else:
            for k, v in it.items():
                if v and not existing.get(k):
                    existing[k] = v
    return list(by_key.values())
def search_pois(center_lat=None, center_lng=None, radius_km=None, rating=None, type_filter=None, keyword=None, province=None, city=None, page=1, page_size=100, compact=False):
    conn = get_conn()
    results = []
    q = "SELECT id,name,rating,city,province,address,lat,lng,description,recommend,source,phone FROM attractions WHERE 1=1"
    p = []
    if rating and rating not in ("all", ""):
        q += " AND rating = ?"
        p.append(rating)
    if keyword:
        q += " AND (name LIKE ? OR city LIKE ?)"
        k = "%" + keyword + "%"
        p.extend([k, k])
    if province:
        q += " AND province = ?"
        p.append(province)
    if city:
        q += " AND city = ?"
        p.append(city)
    q += " ORDER BY CASE rating WHEN '5A' THEN 0 WHEN '4A' THEN 1 WHEN '3A' THEN 2 WHEN '2A' THEN 3 WHEN '\u4e16\u754c\u9057\u4ea7' THEN 0 WHEN '\u56fd\u5bb6\u7ea7\u65c5\u6e38\u5ea6\u5047\u533a' THEN 1 ELSE 4 END, name"
    for row in conn.execute(q, p).fetchall():
        d = dict(row)
        d["type"] = "scenic"
        if compact:
            for k in ("id","recommend","source","created_at"):
                d.pop(k, None)
        if center_lat is not None and radius_km is not None:
            d["distance"] = round(haversine(center_lat, center_lng, d["lat"], d["lng"]), 1)
            if d["distance"] > radius_km:
                continue
        results.append(d)
    # Dedupe attractions to merge same-place different-source entries
    # (e.g., "颐和园" + "北京皇家园林—颐和园", or "泰山" + "山东省泰安市泰山风景区")
    if not keyword and not center_lat:
        results[:] = _dedup_attractions(results)
    fq = "SELECT id,name,city,province,lat,lng,description,address,shop_name,recommend_dish,phone,source FROM foods WHERE 1=1"
    fp = []
    if keyword:
        fq += " AND (name LIKE ? OR city LIKE ?)"
        k = "%" + keyword + "%"
        fp.extend([k, k])
    if province:
        fq += " AND province = ?"
        fp.append(province)
    if city:
        fq += " AND city = ?"
        fp.append(city)
    foods = []
    for row in conn.execute(fq, fp).fetchall():
        d = dict(row)
        d["type"] = "food"
        if compact:
            for k in ("id","phone","recommend_dish","source","created_at"):
                d.pop(k, None)
        if center_lat is not None and radius_km is not None:
            d["distance"] = round(haversine(center_lat, center_lng, d["lat"], d["lng"]), 1)
            if d["distance"] > radius_km:
                continue
        foods.append(d)
    if not keyword and not center_lat:
        foods = _dedup_foods(foods)
    results.extend(foods)
    if type_filter == "scenic":
        results = [r for r in results if r["type"] == "scenic"]
    elif type_filter == "food":
        results = [r for r in results if r["type"] == "food"]
    total = len(results)
    results = results[(page-1)*page_size:page*page_size]
    conn.close()
    return {"total": total, "page": page, "page_size": page_size, "results": results}
def get_stats(center_lat=None, center_lng=None, radius_km=None):
    conn = get_conn()
    scenic = conn.execute("SELECT COUNT(*) FROM attractions").fetchone()[0]
    food = conn.execute("SELECT COUNT(*) FROM foods").fetchone()[0]
    conn.close()
    return {"total": scenic + food, "scenic": scenic, "food": food}
def insert_attractions(items):
    conn = get_conn()
    sql = "INSERT OR IGNORE INTO attractions(name,rating,city,province,address,lat,lng,description,recommend,source,phone) VALUES(?,?,?,?,?,?,?,?,?,?,?)"
    for i in items:
        conn.execute(sql, (i.get("name",""), i.get("rating",""), i.get("city",""), i.get("province",""), i.get("address",""), i.get("lat",0), i.get("lng",0), i.get("description",""), i.get("recommend",""), i.get("source","manual"), i.get("phone","")))
    conn.commit()
    conn.close()
def insert_foods(items):
    conn = get_conn()
    sql = "INSERT OR IGNORE INTO foods(name,city,province,lat,lng,description,address,shop_name,recommend_dish,phone,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)"
    for i in items:
        conn.execute(sql, (i.get("name",""), i.get("city",""), i.get("province",""), i.get("lat",0), i.get("lng",0), i.get("description",""), i.get("address",""), i.get("shop_name",""), i.get("recommend_dish",""), i.get("phone",""), i.get("source","manual")))
    conn.commit()
    conn.close()
