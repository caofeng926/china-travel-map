#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive coordinate correction using OpenStreetMap Photon geocoder.
No API key required. Free public service (https://photon.komoot.io).

Strategy:
  1. Query Photon with multiple variants of the attraction name
  2. Filter to China bounds
  3. Score matches: name similarity + city match + type priority
  4. STRICT city match (penalize mismatches heavily)
  5. Hard distance limit (reject matches > 50km from current coord)
  6. Pick best match per attraction

Usage:
  python3 backend/fix_coords_osm.py --limit N --rate 0.6        # Dry-run on N attractions
  python3 backend/fix_coords_osm.py --commit                    # Apply changes to DB
  python3 backend/fix_coords_osm.py --fix-only-bad --commit     # Only fix clustered coords
  python3 backend/fix_coords_osm.py --report                    # Stats only
"""

import sqlite3
import sys
import os
import json
import time
import urllib.request
import urllib.parse
import argparse
import re
import math

DB_PATHS = ["backend/data/china_travel.db", "data/china_travel.db"]
DB = None
for p in DB_PATHS:
    if os.path.exists(p):
        DB = p
        break
if DB is None:
    print("Database not found", file=sys.stderr)
    sys.exit(1)

PROVINCE_MAP = {
    "北京": "北京市", "上海": "上海市", "天津": "天津市", "重庆": "重庆市",
    "河北": "河北省", "山西": "山西省", "辽宁": "辽宁省", "吉林": "吉林省",
    "黑龙江": "黑龙江省", "江苏": "江苏省", "浙江": "浙江省", "安徽": "安徽省",
    "福建": "福建省", "江西": "江西省", "山东": "山东省", "河南": "河南省",
    "湖北": "湖北省", "湖南": "湖南省", "广东": "广东省", "海南": "海南省",
    "四川": "四川省", "贵州": "贵州省", "云南": "云南省", "陕西": "陕西省",
    "甘肃": "甘肃省", "青海": "青海省", "台湾": "台湾省", "内蒙古": "内蒙古自治区",
    "广西": "广西壮族自治区", "西藏": "西藏自治区", "宁夏": "宁夏回族自治区",
    "新疆": "新疆维吾尔自治区", "兵团": "新疆维吾尔自治区",
}

LAT_MIN, LAT_MAX = 16.0, 56.0
LNG_MIN, LNG_MAX = 70.0, 140.0

TYPE_PRIORITY = {
    "tourism": 100, "leisure": 80, "historic": 95, "natural": 70,
    "place": 30, "waterway": 40, "landuse": 30, "boundary": 20,
    "amenity": 5, "highway": 5, "railway": 5, "building": 1, "aeroway": 5,
}

NAME_SUFFIXES = [
    "景区", "风景区", "旅游区", "度假区", "旅游度假区",
    "国家森林公园", "国家地质公园", "国家级自然保护区",
    "自然保护区", "地质公园", "森林公园", "湿地公园",
    "风景名胜区", "文物保护区", "遗址公园",
    "公园", "古镇", "古村", "古村落",
    "博物馆", "纪念馆", "展览馆", "文化园", "文化馆",
    "寺", "庙", "宫", "塔", "阁",
    "山", "湖", "海", "岛", "湾", "江", "河", "瀑布", "峡谷",
    "广场", "步行街", "商业街", "街区",
]

# Hard limits
DEFAULT_MAX_DISTANCE_KM = 80  # Don't accept matches further than this
DEFAULT_MIN_SCORE = 150


def photon_search(name, lat=None, lon=None, limit=5, retries=3):
    encoded = urllib.parse.quote(name)
    if lat is not None and lon is not None:
        url = f"https://photon.komoot.io/api/?q={encoded}&lat={lat}&lon={lon}&limit={limit}"
    else:
        url = f"https://photon.komoot.io/api/?q={encoded}&limit={limit}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'china-travel-map/1.0 (https://github.com/caofeng926/china-travel-map)',
                'Accept': 'application/json'
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            results = []
            for f in data.get('features', []):
                props = f.get('properties', {})
                geom = f.get('geometry', {}).get('coordinates', [None, None])
                if geom[1] is None or geom[0] is None:
                    continue
                if not (LAT_MIN < geom[1] < LAT_MAX and LNG_MIN < geom[0] < LNG_MAX):
                    continue
                results.append({
                    'lat': geom[1], 'lon': geom[0],
                    'name': props.get('name', ''),
                    'type': props.get('osm_key', ''),
                    'subtype': props.get('osm_value', ''),
                    'city': props.get('city', ''),
                    'state': props.get('state', ''),
                    'country': props.get('country', ''),
                })
            return results
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 + attempt)
    return []


def strip_admin_procs(name):
    """Strip leading administrative/city name from attraction name."""
    # Strip any leading XX省/XX市/XX县/XX区
    m = re.match(r'^([^市县区]{2,8}[市县区])(.+)$', name)
    if m and len(m.group(2)) >= 3:
        return m.group(2)
    return None


def score_result(result, attraction_name, province, city):
    score = 0
    pname = result['name']
    pname_clean = re.sub(r'[（()【】\s]', '', pname).lower()
    aname_clean = re.sub(r'[（()【】\s]', '', attraction_name).lower()

    # Name similarity (most important)
    if pname_clean == aname_clean:
        score += 200
    elif pname_clean and aname_clean:
        if pname_clean in aname_clean or aname_clean in pname_clean:
            score += 100
        else:
            # Common prefix length
            common = 0
            for i in range(min(len(pname_clean), len(aname_clean))):
                if pname_clean[i] == aname_clean[i]:
                    common += 1
                else:
                    break
            score += common * 3

    score += TYPE_PRIORITY.get(result['type'], 0)

    # Province/state match (strict)
    expected_state = PROVINCE_MAP.get(province, province)
    state_match = False
    if expected_state and result['state']:
        state_clean = re.sub(r'[省市区自治区]', '', result['state'])
        exp_clean = re.sub(r'[省市区自治区]', '', expected_state)
        if state_clean and exp_clean and (state_clean in exp_clean or exp_clean in state_clean):
            score += 80
            state_match = True

    # City match (STRICT: heavy penalty for mismatch)
    city_match = False
    if city and result['city']:
        city_clean = re.sub(r'[市县区]', '', city)
        rcity_clean = re.sub(r'[市县区]', '', result['city'])
        if city_clean and rcity_clean:
            if city_clean == rcity_clean or city_clean in rcity_clean or rcity_clean in city_clean:
                score += 100
                city_match = True
            else:
                # Wrong city - heavy penalty
                score -= 500
    elif not result['city']:
        # No city info on result - small penalty (OSM might be incomplete)
        score -= 30

    # State mismatch without city match - extra penalty
    if not state_match and not city_match:
        score -= 200

    return score


def try_shorten_name(name):
    """Generate name variants. Always include the bare name first."""
    variants = [name]

    # Strip parenthetical
    m = re.match(r'^(.+?)[（(].+[）)]$', name)
    if m:
        base = m.group(1)
        if base not in variants and len(base) >= 3:
            variants.append(base)

    # Strip leading admin (省/市/县/区)
    stripped = strip_admin_procs(name)
    if stripped and stripped not in variants and len(stripped) >= 3:
        variants.append(stripped)

    # Strip common suffixes (longest first)
    sorted_suffixes = sorted(NAME_SUFFIXES, key=len, reverse=True)
    for suffix in sorted_suffixes:
        if name.endswith(suffix) and len(name) - len(suffix) >= 3:
            stripped = name[:-len(suffix)]
            if stripped not in variants and len(stripped) >= 3:
                variants.append(stripped)
            # Also try admin-stripped + suffix-stripped
            admin_stripped = strip_admin_procs(stripped)
            if admin_stripped and admin_stripped not in variants and len(admin_stripped) >= 3:
                variants.append(admin_stripped)

    return variants


def geocode_one(name, province, city, current_lat, current_lng, min_score=DEFAULT_MIN_SCORE):
    candidates = []
    variants = try_shorten_name(name)

    for variant in variants:
        results = photon_search(variant, lat=current_lat, lon=current_lng, limit=10)
        if not results and variant == name:
            results = photon_search(variant, limit=10)
        for r in results:
            s = score_result(r, name, province, city)
            if s >= min_score:
                r['score'] = s
                r['variant'] = variant
                candidates.append(r)

    if not candidates:
        return None

    candidates.sort(key=lambda r: r['score'], reverse=True)
    return candidates[0]


def distance_m(lat1, lng1, lat2, lng2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng/2)**2)
    return 2 * R * math.asin(math.sqrt(a))


def main():
    ap = argparse.ArgumentParser(description="Comprehensive coordinate correction via OSM Photon")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--fix-only-bad", action="store_true",
                    help="Only update records where current coords seem suspect")
    ap.add_argument("--rate", type=float, default=0.6)
    ap.add_argument("--source", default=None)
    ap.add_argument("--rating", default=None)
    ap.add_argument("--max-dist", type=float, default=DEFAULT_MAX_DISTANCE_KM, help="Max distance change in km")
    ap.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    _min_score = args.min_score
    _max_dist_km = args.max_dist

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    where_clauses = ["lat IS NOT NULL", "lng IS NOT NULL",
                     "name IS NOT NULL", "TRIM(name) != ''"]
    if args.source:
        where_clauses.append(f"source = '{args.source}'")
    if args.rating:
        where_clauses.append(f"rating = '{args.rating}'")
    where_sql = " AND ".join(where_clauses)

    cur.execute(f"""
        SELECT id, name, rating, city, province, lat, lng, source, address
        FROM attractions WHERE {where_sql}
        ORDER BY id
    """)
    rows = cur.fetchall()

    if args.report:
        cur.execute("SELECT rating, COUNT(*), COUNT(DISTINCT ROUND(lat, 1) || ',' || ROUND(lng, 1)) FROM attractions GROUP BY rating")
        for r in cur.fetchall():
            print(f"  {r[0]}: {r[1]} records, {r[2]} unique coord clusters")
        return

    print(f"Total candidates: {len(rows)}")

    if args.offset:
        rows = rows[args.offset:]
    if args.limit:
        rows = rows[:args.limit]

    if args.fix_only_bad:
        cur.execute("""
            SELECT id FROM attractions
            WHERE (lat, lng) IN (
                SELECT lat, lng FROM attractions
                WHERE lat IS NOT NULL
                GROUP BY ROUND(lat, 2), ROUND(lng, 2)
                HAVING COUNT(*) > 8
            )
        """)
        bad_ids = set(r[0] for r in cur.fetchall())
        print(f"Found {len(bad_ids)} records with potentially wrong (clustered) coordinates")
        rows = [r for r in rows if r[0] in bad_ids]

    print(f"Processing {len(rows)} attractions")
    print("MODE:", "LIVE (will write to DB)" if args.commit else "DRY RUN")

    stats = {"total": 0, "updated": 0, "unchanged": 0, "no_match": 0, "skipped": 0,
             "errors": 0, "rejected_too_far": 0}

    start_time = time.time()
    for idx, row in enumerate(rows):
        aid, name, rating, city, province, cur_lat, cur_lng, source, address = row
        stats["total"] += 1

        if len(name) < 2:
            stats["skipped"] += 1
            continue

        try:
            best = geocode_one(name, province, city, cur_lat, cur_lng, _min_score)
        except Exception as e:
            print(f"  ERROR id={aid} {name}: {e}")
            stats["errors"] += 1
            continue

        if not best:
            stats["no_match"] += 1
            time.sleep(args.rate)
            continue

        dist = distance_m(cur_lat, cur_lng, best['lat'], best['lon'])

        if dist > _max_dist_km * 1000:
            stats["rejected_too_far"] += 1
            if args.verbose:
                print(f"  [{idx+1}/{len(rows)}] REJECTED id={aid} {name}: {dist/1000:.0f}km > {_max_dist_km}km limit")
            time.sleep(args.rate)
            continue

        if dist < 500:
            stats["unchanged"] += 1
            time.sleep(args.rate)
            continue

        stats["updated"] += 1
        print(f"  [{idx+1}/{len(rows)}] id={aid} {name} ({city}): {cur_lat:.4f},{cur_lng:.4f} -> {best['lat']:.4f},{best['lon']:.4f} ({dist/1000:.1f}km) score={best['score']}")

        if args.commit:
            new_address = address
            if not address and best.get('city'):
                state = best.get('state', province)
                new_address = f"{state} {best.get('city')} {best.get('name', name)}".strip()
            elif not address:
                new_address = f"{province} {city} {name}"
            cur.execute("UPDATE attractions SET lat = ?, lng = ?, address = COALESCE(NULLIF(?, ''), address) WHERE id = ?",
                       (best['lat'], best['lon'], new_address, aid))

        time.sleep(args.rate)

        if args.commit and idx % 100 == 99:
            conn.commit()

    if args.commit:
        conn.commit()

    elapsed = time.time() - start_time
    print(f"\n=== Done in {elapsed:.1f}s ===")
    print(f"Stats: {stats}")
    print(f"Rate: {stats['total']/elapsed:.2f} attractions/s")

    conn.close()


if __name__ == "__main__":
    main()
