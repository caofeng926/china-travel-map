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
            recommend TEXT, source TEXT,
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
    conn.commit()
    conn.close()
def haversine(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))
def search_pois(center_lat=None, center_lng=None, radius_km=None, rating=None, type_filter=None, keyword=None, province=None, city=None, page=1, page_size=100, compact=False):
    conn = get_conn()
    results = []
    q = "SELECT * FROM attractions WHERE 1=1"
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
    for row in conn.execute(q, p).fetchall():
        d = dict(row)
        d["type"] = "scenic"
        if compact:
            for k in ("id","recommend","source","created_at"):
                d.pop(k, None)
        if center_lat is not None and radius_km:
            d["distance"] = round(haversine(center_lat, center_lng, d["lat"], d["lng"]), 1)
            if d["distance"] > radius_km:
                continue
        results.append(d)
    fq = "SELECT * FROM foods WHERE 1=1"
    fp = []
    if keyword:
        fq += " AND (name LIKE ? OR city LIKE ?)"
        k = "%" + keyword + "%"
        fp.extend([k, k])
    if province:
        fq += " AND province = ?"
        fp.append(province)
    for row in conn.execute(fq, fp).fetchall():
        d = dict(row)
        d["type"] = "food"
        if compact:
            for k in ("id","phone","recommend_dish","source","created_at"):
                d.pop(k, None)
        if center_lat is not None and radius_km:
            d["distance"] = round(haversine(center_lat, center_lng, d["lat"], d["lng"]), 1)
            if d["distance"] > radius_km:
                continue
        results.append(d)
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
    sql = "INSERT OR IGNORE INTO attractions(name,rating,city,province,address,lat,lng,description,recommend,source) VALUES(?,?,?,?,?,?,?,?,?,?)"
    for i in items:
        conn.execute(sql, (i.get("name",""), i.get("rating",""), i.get("city",""), i.get("province",""), i.get("address",""), i.get("lat",0), i.get("lng",0), i.get("description",""), i.get("recommend",""), i.get("source","manual")))
    conn.commit()
    conn.close()
def insert_foods(items):
    conn = get_conn()
    sql = "INSERT OR IGNORE INTO foods(name,city,province,lat,lng,description,address,shop_name,recommend_dish,phone,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)"
    for i in items:
        conn.execute(sql, (i.get("name",""), i.get("city",""), i.get("province",""), i.get("lat",0), i.get("lng",0), i.get("description",""), i.get("address",""), i.get("shop_name",""), i.get("recommend_dish",""), i.get("phone",""), i.get("source","manual")))
    conn.commit()
    conn.close()
