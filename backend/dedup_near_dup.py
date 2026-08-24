#!/usr/bin/env python3
"""
Strict 4A/5A near-duplicate removal.

Finds pairs of attractions in the same city where:
  1. One name is a substring of the other (>= 40% length ratio), OR
  2. After stripping common suffix (国家地质公园/风景名胜区/风景区/旅游度假区/景区/公园/博物馆/纪念馆/古镇),
     the names match exactly.

Keeps the more descriptive (longer) name; deletes the shorter.

Usage:
  python3 backend/dedup_near_dup.py          # dry-run, list deletions
  python3 backend/dedup_near_dup.py apply   # actually delete

"""
import sqlite3
import sys
import os

# Try multiple paths to find the database
DB_PATHS = [
    "backend/data/china_travel.db",
    "data/china_travel.db",
]
DB = None
for p in DB_PATHS:
    if os.path.exists(p):
        DB = p
        break
if DB is None:
    print("Database not found in:", DB_PATHS)
    sys.exit(1)

conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.execute("""
SELECT id, name, rating, city, province, source
FROM attractions
WHERE rating IN ('4A','5A')
ORDER BY city, rating DESC, id
""")

rows = cur.fetchall()
print(f"Loaded {len(rows)} 4A/5A entries")

by_city = {}
for r in rows:
    cid = r[3]
    by_city.setdefault(cid, []).append(r)

to_delete_ids = set()
seen_pairs = set()
delete_log = []

for city, entries in by_city.items():
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            r1 = entries[i]
            r2 = entries[j]
            id1, n1 = r1[0], r1[1]
            id2, n2 = r2[0], r2[1]
            if id1 == id2:
                continue
            if id1 in to_delete_ids or id2 in to_delete_ids:
                continue
            if r1[2] != r2[2]:
                continue
            key = (min(id1, id2), max(id1, id2))
            if key in seen_pairs:
                continue
            n1_clean = (n1.replace('（', '(').replace('）', ')').replace(' ', '').replace('·', ''))
            n2_clean = (n2.replace('（', '(').replace('）', ')').replace(' ', '').replace('·', ''))

            longer, shorter = (n1_clean, n2_clean) if len(n1_clean) >= len(n2_clean) else (n2_clean, n1_clean)
            longer_id = id1 if len(n1_clean) >= len(n2_clean) else id2
            shorter_id = id2 if longer_id == id1 else id1

            if shorter in longer and len(shorter) >= 3:
                ratio = len(shorter) / len(longer)
                if ratio >= 0.4:
                    seen_pairs.add(key)
                    to_delete_ids.add(shorter_id)
                    delete_log.append((shorter_id, longer_id,
                                        n1 if shorter_id == id1 else n2,
                                        n2 if shorter_id == id2 else n1,
                                        city, r1[2]))
                    continue

            suffixes = ['国家地质公园', '风景名胜区', '风景区', '旅游度假区', '度假区',
                        '旅游区', '景区', '公园', '博物馆', '纪念馆', '古镇']
            for suf in suffixes:
                n1_s = n1_clean[:-len(suf)] if n1_clean.endswith(suf) else None
                n2_s = n2_clean[:-len(suf)] if n2_clean.endswith(suf) else None
                if n1_s and n2_s and n1_s == n2_s and len(n1_s) >= 3:
                    seen_pairs.add(key)
                    longer_id2 = id1 if len(n1_clean) >= len(n2_clean) else id2
                    shorter_id2 = id2 if longer_id2 == id1 else id1
                    to_delete_ids.add(shorter_id2)
                    delete_log.append((shorter_id2, longer_id2,
                                        n1 if shorter_id2 == id1 else n2,
                                        n2 if shorter_id2 == id2 else n1,
                                        city, r1[2]))
                    break

print(f"Found {len(to_delete_ids)} unique duplicates to delete (from {len(delete_log)} pairs)")
for d in delete_log:
    print(f"  Delete id={d[0]} '{d[2]}' (keep id={d[1]} '{d[3]}' in {d[4]}, {d[5]})")

if len(sys.argv) > 1 and sys.argv[1] == 'apply':
    cur.executemany("DELETE FROM attractions WHERE id = ?", [(d[0],) for d in delete_log])
    conn.commit()
    print(f"Deleted {len(to_delete_ids)} records")
    cur.execute("SELECT COUNT(*) FROM attractions")
    print(f"Remaining: {cur.fetchone()[0]}")
else:
    print("\nDRY RUN. Use 'apply' argument to actually delete.")

conn.close()
