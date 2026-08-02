"""Trip Planner - Route planning & POI along route search"""
import json, urllib.request, urllib.parse, math, time, os
from database import get_conn, haversine, DB_PATH

AMAP_KEY = os.environ.get("AMAP_KEY", "")
SEARCH_RADIUS = 15  # km

def _require_amap_key():
    if not AMAP_KEY:
        raise RuntimeError(
            "AMAP_KEY environment variable not set. "
            "Copy .env.example to .env and set your AMap Web Service API Key."
        )

def geocode(address):
    _require_amap_key()
    url = f"https://restapi.amap.com/v3/geocode/geo?key={AMAP_KEY}&address={urllib.parse.quote(address)}&output=JSON"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data["status"] == "1" and data["geocodes"]:
                loc = data["geocodes"][0]["location"].split(",")
                return float(loc[1]), float(loc[0]), data["geocodes"][0].get("formatted_address", address)
    except Exception as e:
        print(f"Geocode error for {address}: {e}")
    return None, None, address

def get_driving_route(origin_lat, origin_lng, dest_lat, dest_lng):
    _require_amap_key()
    origin = f"{origin_lng},{origin_lat}"
    dest = f"{dest_lng},{dest_lat}"
    url = (f"https://restapi.amap.com/v3/direction/driving?key={AMAP_KEY}"
           f"&origin={origin}&destination={dest}&strategy=0&extensions=all&output=JSON")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            if data["status"] == "1" and data.get("route", {}).get("paths"):
                path = data["route"]["paths"][0]
                polyline = []
                for step in path.get("steps", []):
                    for point in step.get("polyline", "").split(";"):
                        if point:
                            lng, lat = point.split(",")
                            polyline.append((float(lat), float(lng)))
                dur = int(path.get("duration", 0))
                dist = int(path.get("distance", 0))
                return {"polyline": polyline, "duration": dur, "distance": dist,
                        "duration_text": f"{dur//3600}\u5c0f\u65f6{(dur%3600)//60}\u5206",
                        "distance_text": f"{dist/1000:.0f}\u516c\u91cc"}
    except Exception as e:
        print(f"Driving route error: {e}")
    return None

def get_transit_route(origin_lat, origin_lng, dest_lat, dest_lng, city=""):
    _require_amap_key()
    origin = f"{origin_lng},{origin_lat}"
    dest = f"{dest_lng},{dest_lat}"
    url = (f"https://restapi.amap.com/v3/direction/transit/integrated?key={AMAP_KEY}"
           f"&origin={origin}&destination={dest}&city={urllib.parse.quote(city)}&output=JSON")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            if data["status"] == "1" and data.get("route", {}).get("transits"):
                t = data["route"]["transits"][0]
                dur = int(t.get("duration", 0))
                polyline = []
                for seg in t.get("segments", []):
                    seg_pts = []
                    if "walking" in seg:
                        for step in seg["walking"].get("steps", []):
                            for pt in step.get("polyline", "").split(";"):
                                if pt:
                                    l, a = pt.split(",")
                                    seg_pts.append((float(a), float(l)))
                    elif "bus" in seg:
                        for bl in seg["bus"].get("buslines", []):
                            for pt in bl.get("polyline", "").split(";"):
                                if pt:
                                    l, a = pt.split(",")
                                    seg_pts.append((float(a), float(l)))
                            if seg_pts:
                                break  # use first busline only to avoid duplicates
                    elif "railway" in seg:
                        rail = seg["railway"]
                        for stop in rail.get("via_stops", []) + [rail]:
                            for pt in stop.get("location", stop.get("polyline", "")).split(";"):
                                if pt:
                                    l, a = pt.split(",")
                                    seg_pts.append((float(a), float(l)))
                    # Drop leading dup so segments join smoothly
                    if seg_pts and polyline and polyline[-1] == seg_pts[0]:
                        seg_pts = seg_pts[1:]
                    polyline.extend(seg_pts)
                if not polyline:
                    polyline = _interpolate(origin_lat, origin_lng, dest_lat, dest_lng)
                return {"polyline": polyline, "duration": dur, "distance": 0,
                        "duration_text": f"{dur//3600}\u5c0f\u65f6{(dur%3600)//60}\u5206",
                        "distance_text": "\u516c\u5171\u4ea4\u901a"}
    except Exception as e:
        print(f"Transit route error: {e}")
    return None

def _interpolate(lat1, lng1, lat2, lng2, n=30):
    """Spherical linear interpolation between two coordinates.

    Returns n+1 evenly-spaced points along the great-circle arc connecting
    (lat1,lng1) and (lat2,lng2). More accurate than naive linear interp at
    long distances; intended for sub-1000 km route fallbacks.
    """
    lat1r, lng1r = math.radians(lat1), math.radians(lng1)
    lat2r, lng2r = math.radians(lat2), math.radians(lng2)
    dlat = lat2r - lat1r
    dlng = lng2r - lng1r
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlng / 2) ** 2
    c = 2 * math.asin(math.sqrt(h))
    if c == 0:
        return [(lat1, lng1)] * (n + 1)
    points = []
    for i in range(n + 1):
        f = i / n
        s1 = math.sin((1 - f) * c) / math.sin(c)
        s2 = math.sin(f * c) / math.sin(c)
        x = s1 * math.cos(lat1r) * math.cos(lng1r) + s2 * math.cos(lat2r) * math.cos(lng2r)
        y = s1 * math.cos(lat1r) * math.sin(lng1r) + s2 * math.cos(lat2r) * math.sin(lng2r)
        z = s1 * math.sin(lat1r) + s2 * math.sin(lat2r)
        ilat = math.atan2(z, math.sqrt(x * x + y * y))
        ilng = math.atan2(y, x)
        points.append((math.degrees(ilat), math.degrees(ilng)))
    return points

def sample_polyline(polyline, interval_km=10):
    if not polyline: return []
    samples = [polyline[0]]
    acc = 0
    for i in range(1, len(polyline)):
        d = haversine(polyline[i-1][0], polyline[i-1][1], polyline[i][0], polyline[i][1])
        acc += d
        if acc >= interval_km:
            samples.append(polyline[i])
            acc = 0
    if len(samples) > 1 and samples[-1] != polyline[-1]:
        samples.append(polyline[-1])
    return samples

def find_pois_along_route(polyline):
    samples = sample_polyline(polyline, interval_km=8)
    if not samples:
        return []
    conn = get_conn()
    seen = set()
    pois = []
    lats = [p[0] for p in samples]
    lngs = [p[1] for p in samples]
    min_lat, max_lat = min(lats), max(lats)
    min_lng, max_lng = min(lngs), max(lngs)
    avg_lat = (min_lat + max_lat) / 2
    # Padding shrunk from +0.5 to +0.05 deg (~5.5 km); large padding caused
    # bbox queries to return thousands of rows across China-wide trips.
    dlat = SEARCH_RADIUS / 111.0 + 0.05
    dlng = SEARCH_RADIUS / (111.0 * math.cos(math.radians(avg_lat))) + 0.05
    min_lat -= dlat
    max_lat += dlat
    min_lng -= dlng
    max_lng += dlng
    cur = conn.execute(
        "SELECT id,name,rating,city,province,address,lat,lng,description FROM attractions WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?",
        (min_lat, max_lat, min_lng, max_lng)
    )
    attraction_rows = cur.fetchall()
    cur2 = conn.execute(
        "SELECT id,name,city,province,lat,lng,description,address,shop_name FROM foods WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?",
        (min_lat, max_lat, min_lng, max_lng)
    )
    food_rows = cur2.fetchall()
    # Convert rows to dicts once (was rebuilt every sample iteration) and
    # pre-compute a squared-degree distance for fast pre-filter.
    attractions = []
    for row in attraction_rows:
        attractions.append(dict(row))
    foods = []
    for row in food_rows:
        foods.append(dict(row))
    # crude angular distance threshold squared (degrees)
    thresh_lat = SEARCH_RADIUS / 111.0
    thresh_lng = SEARCH_RADIUS / (111.0 * math.cos(math.radians(avg_lat)))
    thresh_sq = thresh_lat * thresh_lat + thresh_lng * thresh_lng
    for lat, lng in samples:
        for d in attractions:
            if (lat - d["lat"]) ** 2 + (lng - d["lng"]) ** 2 > thresh_sq:
                continue
            dist = haversine(lat, lng, d["lat"], d["lng"])
            key = f"a_{d['id']}"
            if dist <= SEARCH_RADIUS and key not in seen:
                seen.add(key)
                d["distance"] = round(dist, 1)
                d["type"] = "scenic"
                d["cat"] = "\u666f\u533a"
                pois.append(d)
        for d in foods:
            if (lat - d["lat"]) ** 2 + (lng - d["lng"]) ** 2 > thresh_sq:
                continue
            dist = haversine(lat, lng, d["lat"], d["lng"])
            key = f"f_{d['id']}"
            if dist <= SEARCH_RADIUS and key not in seen:
                seen.add(key)
                d["distance"] = round(dist, 1)
                d["type"] = "food"
                d["cat"] = "\u7f8e\u98df"
                pois.append(d)
    conn.close()
    if polyline:
        rl, rn = polyline[0]
        pois.sort(key=lambda p: haversine(rl, rn, p["lat"], p["lng"]))
    return pois

def split_into_days(pois, total_sec, polyline):
    h = total_sec / 3600
    if h <= 3:
        return [{"day": 1, "title": "\u5f53\u65e5\u884c\u7a0b", "pois": pois}]
    nd = 2 if h <= 6 else max(2, int(math.ceil(h / 4)))
    if not pois:
        return [{"day": d+1, "title": f"\u7b2c{d+1}\u5929", "pois": []} for d in range(nd)]
    # Build cumulative arc-length table along polyline (km) so we can map
    # each POI to the nearest point on the actual route, not just its
    # straight-line distance from the start (the old heuristic over- or
    # under-assigned POIs to early days).
    cum = [0.0]
    for i in range(1, len(polyline)):
        cum.append(cum[-1] + haversine(polyline[i-1][0], polyline[i-1][1],
                                       polyline[i][0], polyline[i][1]))
    total = cum[-1] if cum else 0.0
    for p in pois:
        if total <= 0 or len(polyline) == 1:
            arc = 0.0
        else:
            best_i, best_d = 0, float("inf")
            plat, plng = p["lat"], p["lng"]
            for i, (pp_lat, pp_lng) in enumerate(polyline):
                dd = (pp_lat - plat) ** 2 + (pp_lng - plng) ** 2
                if dd < best_d:
                    best_d = dd
                    best_i = i
            arc = cum[best_i]
        pct = arc / total if total > 0 else 0
        p["day"] = min(int(pct * nd), nd - 1) + 1
    return [{"day": d+1, "title": f"\u7b2c{d+1}\u5929", "pois": [p for p in pois if p.get("day") == d+1]} for d in range(nd)]

def plan_trip(origin_name, dest_name, mode="driving"):
    olat, olng, oname = geocode(origin_name)
    dlat, dlng, dname = geocode(dest_name)
    if not olat or not dlat:
        return {"error": f"\u65e0\u6cd5\u5b9a\u4f4d: {origin_name if not olat else dest_name}"}
    if mode == "driving":
        route = get_driving_route(olat, olng, dlat, dlng)
    else:
        route = get_transit_route(olat, olng, dlat, dlng)
    if not route:
        return {"error": f"\u65e0\u6cd5\u89c4\u5212\u8def\u7ebf"}
    pois = find_pois_along_route(route["polyline"])
    days = split_into_days(pois, route["duration"], route["polyline"])
    return {
        "origin": {"name": oname, "lat": olat, "lng": olng},
        "destination": {"name": dname, "lat": dlat, "lng": dlng},
        "route": {"polyline": route["polyline"], "duration": route["duration"],
                  "distance": route["distance"], "duration_text": route["duration_text"],
                  "distance_text": route["distance_text"], "mode": mode},
        "days": days, "total_pois": len(pois),
        "stats": {"scenic": sum(1 for p in pois if p["type"]=="scenic"), "food": sum(1 for p in pois if p["type"]=="food")}
    }