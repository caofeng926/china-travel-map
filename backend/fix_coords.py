#!/usr/bin/env python3
"""
用高德 geocode API 校正数据库中所有景点的坐标。
需要环境变量 AMAP_KEY。

用法:
  export AMAP_KEY=<你的高德Web服务API key>
  python3 /tmp/fix_coords.py [--limit N] [--dry-run]

参数:
  --limit N: 只校正前 N 条（调试用）
  --dry-run: 只检查不更新
  --source <src>: 只校正特定 source 的记录
  --city-only: 用 city 名搜索（不用景区名）
"""
import sys, os, time, json, argparse
sys.path.insert(0, '/Users/caofeng/AIwork/中国旅游地图/china-travel-map/backend')
import urllib.request, urllib.parse
import sqlite3
import threading

# 必须设置 AMAP_KEY
AMAP_KEY = os.environ.get("AMAP_KEY", "")
if not AMAP_KEY:
    print("错误: 需要设置环境变量 AMAP_KEY", file=sys.stderr)
    sys.exit(1)

# 高德 QPS 限制: 个人 3 QPS, 商用 50+ QPS
QPS = float(os.environ.get("AMAP_QPS", "3"))

# 重试次数
MAX_RETRY = 3

def geocode(address, city=None):
    """调用高德 geocode API，返回 (lng, lat) 或 None"""
    params = {
        'key': AMAP_KEY,
        'address': address,
        'output': 'JSON',
    }
    if city:
        params['city'] = city
    url = "https://restapi.amap.com/v3/geocode/geo?" + urllib.parse.urlencode(params)
    
    for attempt in range(MAX_RETRY):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'china-travel-map/fix_coords.py'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            if data.get('status') == '1' and data.get('geocodes'):
                loc = data['geocodes'][0]['location']
                lng, lat = loc.split(',')
                return float(lng), float(lat)
            elif data.get('status') == '0':
                # 限流等错误
                if data.get('infocode') in ('10001', '10003', '10004'):  # invalid key / quota
                    print(f"  KEY/QUOTA 错误: {data.get('info')}", file=sys.stderr)
                    return None
                # 其他错误跳过
                return None
        except Exception as e:
            if attempt == MAX_RETRY - 1:
                print(f"  网络错误: {e}", file=sys.stderr)
            time.sleep(0.5)
    return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0, help='限制处理数量')
    parser.add_argument('--dry-run', action='store_true', help='只检查不更新')
    parser.add_argument('--source', default=None, help='只处理特定 source')
    parser.add_argument('--city-only', action='store_true', help='只用 city 名搜索')
    args = parser.parse_args()
    
    conn = sqlite3.connect('/Users/caofeng/AIwork/中国旅游地图/china-travel-map/backend/data/china_travel.db')
    conn.row_factory = sqlite3.Row
    
    # 找出疑似坐标不准确的记录（外部数据集的）
    q = "SELECT id, name, city, province, lat, lng, source FROM attractions WHERE 1=1"
    p = []
    if args.source:
        q += " AND source = ?"
        p.append(args.source)
    q += " ORDER BY id"
    if args.limit:
        q += f" LIMIT {args.limit}"
    
    rows = conn.execute(q, p).fetchall()
    print(f"待处理: {len(rows)} 条 (QPS={QPS})")
    
    fixed = 0
    skipped = 0
    failed = 0
    last_call = 0
    
    for i, r in enumerate(rows):
        name = r['name']
        city = r['city']
        province = r['province']
        old_lat = r['lat']
        old_lng = r['lng']
        
        # 构造查询地址（先景区名+城市，再只用城市）
        if args.city_only or not name:
            address = city + province
        else:
            address = name
        
        # 限流
        elapsed = time.time() - last_call
        if elapsed < 1/QPS:
            time.sleep(1/QPS - elapsed)
        
        result = geocode(address, city=city if city else None)
        last_call = time.time()
        
        if not result:
            failed += 1
            continue
        
        new_lng, new_lat = result
        
        # 检查变化（>1km 才更新，避免噪声）
        if old_lat and old_lng:
            import math
            d = math.hypot((new_lat - old_lat) * 111, (new_lng - old_lng) * 111 * math.cos(math.radians(new_lat)))
            if d < 1:  # 变化小于 1km 不更新
                skipped += 1
                continue
        
        if not args.dry_run:
            conn.execute("UPDATE attractions SET lat=?, lng=? WHERE id=?", (new_lat, new_lng, r['id']))
        fixed += 1
        
        if i % 50 == 0:
            print(f"  [{i+1}/{len(rows)}] fixed={fixed} skip={skipped} fail={failed}")
    
    if not args.dry_run:
        conn.commit()
    conn.close()
    
    print(f"\n完成: fixed={fixed} skipped={skipped} failed={failed}")

if __name__ == '__main__':
    main()
