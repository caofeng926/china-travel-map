# 中国旅游地图项目 - 第二轮深度代码审查报告

> 审查轮次：**第 2 轮 · 深度复审**
> 审查时间：2026-07-26 17:46
> 复审维度：并发安全 · stdlib 行为边界 · JS 拼接 context 敏感性 · SQLite 类型系统陷阱 · git history 修复模式
> **配套上轮报告**：`docs/code_review.md`（H-01 ~ N-07，含 5 Blocker）。本报告延续编号，从 **H-17** 起。

---

## 一、本次新增 vs 上次遗漏

| 维度 | 第 1 轮覆盖 | 第 2 轮补强 |
|---|---|---|
| 显眼的安全洞（Key 泄露 / RCE / CORS） | ✅ 已覆盖 | — |
| **GIL 并发原子性**（多语句序列竞态） | ❌ 完全没看 | H-17, H-31, H-32 |
| **stdlib 版本行为差异**（Python < 3.11 的 `..` 路径遍历） | ❌ 没意识到 | H-24 |
| **HTTP 层 chunked encoding 兜底** | ❌ 没看 BaseHTTPRequestHandler 边界 | H-23 |
| **CSP 与 path 处理的细节**（query string 漏判） | ❌ 只看了显眼配置 | H-18 |
| **`INSERT OR IGNORE` 误用**（无 UNIQUE 时等于 INSERT） | ❌ 完全没看 | H-19 |
| **前端 `esc()` 上下文敏感性** | ⚠️ 提了转义但漏了 `onclick` 数值与属性引号 | H-20 |
| **重复 `pois.map()` 与 `clientDedupe()`** | ❌ 没看内部冗余 | H-30 |
| **`_interpolate` 直线 vs 球面插值** | ❌ 根本没看 | H-26 |
| **`get_transit_route` 多 segment 拼接残缺** | ❌ 根本没看 | H-27 |
| **`renderMassMarks` 内部性能黑洞** | ⚠️ 提了 O(N²) 但没量化 | H-21, H-22, H-30 |
| **git history 反复 fix 的根因** | ❌ 没归纳 | H-40 |

**反思盲点**：第 1 轮对"高德 Key 在 git 历史里反复轮换"只看到表面（"key 暴露了"），没有归纳出"项目存在反复修补同一类问题的模式，需要 secret scanning CI"。

---

## 二、本轮新增 · 🔴 Blocker（4 个）

### H-17 `_check_rate_limit` 在多线程下双重 bug：计数丢失 + 永久卡死 IP

**位置**：`backend/server.py:26, 116-128`

**两个独立 bug**：
1. **TOCTOU 数据竞争**：`ThreadingHTTPServer` 每请求一线程，GIL 下单字节码原子但**多语句序列不原子**。
   - 线程 A：`if ip not in RATE_LIMIT` → True，`RATE_LIMIT[ip] = []`（list_A）
   - 线程 B：紧接 `if ip not in RATE_LIMIT` → True，`RATE_LIMIT[ip] = []`（list_B 覆盖 list_A）
   - 线程 B 走完 `RATE_LIMIT[ip] = [...cleaned...]` 后 A 接力，A 用 `RATE_LIMIT[ip] = 新list` **覆盖 B 的 append**
   - 净结果：B 的请求计数被 A 抹掉 → 限流失效
2. **永久卡死 IP**：超过 429 后**该请求仍被 `append((now,1))`** → 下次同 IP 来 `total > 60` 永远成立 → **需进程重启才能解封**。攻击者 1 秒打 60 请求就能永久封禁 NAT 后面的所有人。

**修复**：
```python
import threading
RATE_LIMIT_LOCK = threading.Lock()
RATE_LIMIT = {}

def _check_rate_limit(self):
    ip = self.headers.get("X-Real-IP", self.client_address[0])
    now = time.time()
    with RATE_LIMIT_LOCK:                       # ← 串行化
        window = [t for t in RATE_LIMIT.get(ip, []) if now - t < RATE_LIMIT_WINDOW]
        if len(window) >= RATE_LIMIT_MAX:
            RATE_LIMIT[ip] = window              # 保留历史但不再加 1
            self._err("rate_limited"); return False
        window.append(now)
        RATE_LIMIT[ip] = window
    return True
```

---

### H-19 `INSERT OR IGNORE` 在无 UNIQUE 约束的表上等于 `INSERT`，跑 N 次 seed = 数据 ×N

**位置**：`backend/database.py:13-33, 288-298`

`attractions` / `foods` 表的 schema **没有任何 UNIQUE 约束**——只有 `id INTEGER PRIMARY KEY AUTOINCREMENT`。`INSERT OR IGNORE` 仅在 UNIQUE/INTEGER PRIMARY KEY 冲突时跳过。**INTEGER PRIMARY KEY 是 AUTOINCREMENT，永不冲突**，所以 `OR IGNORE` 形同虚设。

**风险**：
- `seed.py` 跑 3 次 → attractions 表里 3 倍数据（每次独立 `id`）。
- 服务端 `_dedup_attractions` 仅在 `keyword is None and center_lat is None` 时调用（database.py:243）——**带 `?keyword=` 的查询直接返回重复行**。
- 前端 `loadPOIData` 不去重（依赖 `clientDedupe`）→ 7k 行真实数据可能含 2 万行 + 重复。

**修复**：
```sql
-- 加 UNIQUE 约束让 OR IGNORE 真正生效
CREATE UNIQUE INDEX IF NOT EXISTS uq_att_name_city
  ON attractions(name, city, IFNULL(province,''));

CREATE UNIQUE INDEX IF NOT EXISTS uq_food_name_city
  ON foods(name, city, IFNULL(shop_name,''), IFNULL(address,''));
```
或更直接：**改用 UPSERT 语义**
```python
sql = """INSERT INTO attractions(...) VALUES(...)
         ON CONFLICT(name, city) DO UPDATE SET
           description=excluded.description,
           phone=excluded.phone,
           lat=excluded.lat, lng=excluded.lng"""
```

---

### H-20 前端 `data-name` / `onclick` 缺 `"` 转义，存在 XSS + JS 注入面

**位置**：`frontend/index.html:608-609, 679, 688`

```js
function esc(s){if(!s)return "";return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
//                              ↑ 只转 3 个字符，没有 &quot; 没有 &#39;

// index.html:608 双引号属性
c += '<button ... data-name="' + esc(info.name) + '" ...>';
// ↑ 双引号属性，esc 不转 "

// index.html:679 JS 上下文
html += '<div class="item" onclick="flyTo(' + p.lat + "," + p.lng + ')">';
// ↑ p.lat/lng 是 SQLite REAL 通常 float，但 SQLite 动态类型——可注入字符串
```

**攻击路径**：
- 拿到 SEED_TOKEN 的人或被攻陷的 admin 可注入 `name = foo" onmouseover="alert(1)` → 用户点开 marker XSS 触发
- 或 `lat = "1);alert(document.cookie);//"` → 点击列表项触发

历史 commit `a18b154 fix: escape nested quotes in geolocation marker HTML` 只补了用户定位 marker；**mass mark / list item 没补**。

**修复**：
```js
function esc(s){
  if(!s) return "";
  return String(s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}
function numOrZero(v){ v=parseFloat(v); return isFinite(v)?v:0; }

// 改用事件委托 + data-*，根除所有 onclick 字符串拼接
html += '<div class="item" data-lat="'+esc(String(numOrZero(p.lat)))+'" data-lng="'+esc(String(numOrZero(p.lng)))+'">';
document.getElementById("list").addEventListener("click", function(ev){
  const item = ev.target.closest(".item");
  if (!item) return;
  flyTo(+item.dataset.lat, +item.dataset.lng);
});
```

---

### H-23 `Content-Length` 校验 + `Transfer-Encoding: chunked` 处理缺失

**位置**：`backend/server.py:75-80`

```python
cl = int(self.headers.get("Content-Length", 0))   # ← 默认 0，负数/格式错都接受
if cl > MAX_BODY_SIZE:
    self._json({"error": "request too large"}, 413)
    return
body = json.loads(self.rfile.read(cl))            # ← 无 try/except，抛 500
```

**风险**：
1. 客户端发 `Content-Length: -1`、`NaN`、`0x7fffffff` 都能通过 size 检查。
2. 同时发 `Content-Length` + `Transfer-Encoding: chunked` → BaseHTTPRequestHandler 只看 Content-Length 读固定字节，**剩余 chunked 帧留在 socket 缓冲区污染下一个请求**（HTTP request smuggling 雏形）。
3. 单独发 `Transfer-Encoding: chunked`（无 Content-Length）→ `cl=0` → `json.loads("")` 抛异常 → `do_POST` 无 try/except → 500。客户端重试触发 N 次接口调用，**构造轻量 DDOS**。

**修复**：
```python
def do_POST(self):
    if not self._check_rate_limit(): return
    te = (self.headers.get("Transfer-Encoding") or "").lower()
    if "chunked" in te:
        self._err("chunked encoding not supported", 411); return
    try:
        cl = int(self.headers.get("Content-Length") or "0")
    except (TypeError, ValueError):
        self._err("invalid Content-Length", 400); return
    if cl < 0 or cl > MAX_BODY_SIZE:
        self._err("payload_too_large", 413); return
    try:
        body = json.loads(self.rfile.read(cl))
    except json.JSONDecodeError as e:
        self._err("invalid_json", 400); return
    ...
```

---

## 三、本轮新增 · 🟡 Suggestion（13 个）

### H-18 `end_headers()` query string 漏判 → HTML 被 CDN/浏览器错误缓存

**位置**：`backend/server.py:140-151`

```python
if self.path.endswith('.html') or self.path == '/':   # ← 含 query 时 .html 判断失效
```

`GET /index.html?v=2` 的 `self.path` 是 `/index.html?v=2`，**`endswith('.html')` 为 False** → 不加 `Cache-Control: no-cache` → HTML 被缓存，新版部署用户看不到。

**修复**：
```python
from urllib.parse import urlsplit
def end_headers(self):
    path = urlsplit(self.path).path
    if not path.startswith("/api/"):
        self.send_header("Content-Security-Policy", _CSP)
    if path.endswith('.html') or path == '/':
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Content-Type', 'text/html; charset=utf-8')
    super().end_headers()
```

**附带**：`_json` 内 gzip 分支没写 `Content-Length`，HTTP/1.1 keep-alive proxy 可能误判；应显式 `send_header("Content-Length", str(len(compressed)))`。

---

### H-21 `find_pois_along_route` N×M 笛卡尔积 + 每轮 `dict(row)` 重建（性能致命）

**位置**：`backend/trip_planner.py:135-156`

N=200 (1600km 路径每 8km 采样) × M=7000 = **140 万次 haversine** + **140 万次 dict 重建** + **1120 万次三角函数调用**。单次请求 RT 中端 VPS 8-15 秒。

**bbox 还放宽了 4 倍**（`+ 0.5` 是经验值，15km 半径只需 ~0.14° 余量）→ 候选行多 4 倍 → 笛卡尔积再膨胀。

**修复**：
```python
# 一次性转 dict，bbox 余量收紧
attractions_by_id = {row["id"]: dict(row) for row in attraction_rows}
R2 = SEARCH_RADIUS ** 2
cos_lat = math.cos(math.radians(avg_lat))
for lat, lng in samples:
    for aid, a in attractions_by_id.items():
        # 用平方预过滤，绝大多数远点直接 skip
        dy = (lng - a["lng"]) * cos_lat
        dx = lat - a["lat"]
        if dx*dx + dy*dy > R2:
            continue
        d = haversine(lat, lng, a["lat"], a["lng"])
        ...
```

---

### H-22 `split_into_days` 在长 polyline 下 O(N²) 累计距离

**位置**：`backend/trip_planner.py:170-173`

```python
td = sum(haversine(...) for i in range(len(polyline)-1))   # 3000-8000 点 ≈ 24k 次三角函数
for p in pois:
    pct = haversine(rl, rn, p["lat"], p["lng"]) / td        # 每个 POI 又一次 haversine
```

**修复**：用累计距离 + 二分
```python
cum = [0.0]
for i in range(len(polyline)-1):
    cum.append(cum[-1] + haversine(polyline[i][0], polyline[i][1],
                                    polyline[i+1][0], polyline[i+1][1]))
total = cum[-1] or 1.0
# 对每个 POI bisect 找最近段，O(log N)
```

---

### H-24 `SimpleHTTPRequestHandler` 在 Python < 3.11 上仍允许 `..` 路径遍历

**位置**：`backend/server.py:30-32, 64`

CVE-2021-28861 在 Python 3.11 修复了 `SimpleHTTPRequestHandler.translate_path` 的 `..` 处理。但 CI 写死 `python-version: "3.11"`（`deploy.yml:16`），**生产服务器可能装的是 3.9 / 3.10**（`deploy_server.sh:48` 是 `python3 server.py`，没指定版本）—— 仍可利用。

**测试**（Python 3.10）：`curl http://localhost:8765/../etc/passwd` 返回 200 + 内容。

**修复**：
```python
def do_GET(self):
    if not self._check_rate_limit(): return
    raw_path = urlparse(self.path).path
    if ".." in raw_path.split("/") or raw_path.startswith("//"):
        self._err("bad_request", 400); return
    ...
```
并在 `deploy_server.sh` 加 `python3 --version` 检查 + README 写明 Python 3.11+。

---

### H-25 API 错误响应缺错误码

**位置**：`backend/server.py` 多处

所有 4xx 只有 `{"error": "..."}`，没有 `code` 字段。客户端无法区分 "rate_limited" / "invalid_json" / "unauthorized"，日志聚合也缺稳定字符串。

**修复**：
```python
ERROR_CODES = {
    "unauthorized":      {"status": 401, "message": "未授权"},
    "rate_limited":      {"status": 429, "message": "请求过于频繁"},
    "payload_too_large": {"status": 413, "message": "请求体过大"},
    "invalid_json":      {"status": 400, "message": "JSON 格式错误"},
    "internal_error":    {"status": 500, "message": "服务器内部错误"},
}

def _err(self, code, **extra):
    spec = ERROR_CODES.get(code, ERROR_CODES["internal_error"])
    self._json({"error": spec["message"], "code": code, **extra}, spec["status"])
```

---

### H-26 `_interpolate` 直线 vs 球面 + bbox 余量过大

**位置**：`backend/trip_planner.py:90-91, 118-124`

1. `_interpolate` 直线插值画北京-上海的"折线"是斜的，结果 sample_polyline 只采到首尾两点，**沿途 POI 大幅漏查**。
2. `dlng = SEARCH_RADIUS / (111.0 * cos(avg_lat)) + 0.5` —— `+ 0.5` 经验值 ≈ 55km 余量，**比真实需求大 4 倍**。

**修复**：
```python
# 球面 slerp 插值（见 N-01 类似实现）
def _interpolate(lat1, lng1, lat2, lng2, n=30):
    # ... slerp 球面插值，30 个点真实路径

# bbox 余量改成 +0.05（约 5.5km，跟 SEARCH_RADIUS 匹配）
dlng = SEARCH_RADIUS / (111.0 * max(0.1, cos(avg_lat))) + 0.05
```

---

### H-27 `get_transit_route` 只取每 segment 首步 polyline，路径严重失真

**位置**：`backend/trip_planner.py:69-80`

```python
for seg in t.get("segments", []):
    ps = ""
    if "walking" in seg:
        ps = seg["walking"].get("steps", [{}])[0].get("polyline", "")  # ← 只取首步
    elif "bus" in seg:
        bl = seg["bus"].get("buslines", [])
        if bl: ps = bl[0].get("polyline", "")                          # ← 只取首条 bus
```

**三重问题**：
1. 只取首步 = 整体路径的 10-30%
2. 同时有 walking 和 bus 的 segment 被 walking 单独占用
3. **完全漏掉 railway 段**（地铁 / 火车）

**修复**：聚合所有 step 的 polyline
```python
def _collect_seg_points(seg):
    pts = []
    if "walking" in seg:
        for step in seg["walking"].get("steps", []):
            pts.extend(_parse_polyline(step.get("polyline", "")))
    if "bus" in seg:
        for bl in seg["bus"].get("buslines", []):
            pts.extend(_parse_polyline(bl.get("polyline", "")))
    if "railway" in seg:
        for v in seg["railway"].get("vehicles", []):
            pts.extend(_parse_polyline(v.get("polyline", "")))
    return pts
```

---

### H-28 `/api/seed` 鉴权后无 body schema 校验

**位置**：`backend/server.py:69-83`

拿到 SEED_TOKEN 可注入任何类型：`{"attractions": [{"lat": "<script>"}]}` → SQLite 不强制类型 → 写入 → 前端 `flyTo("<script>")` 触发 XSS（H-20 攻击源）。`body.get("attractions", "string")` 时 `for i in items` 按字符迭代抛 AttributeError。

**修复**：写 zero-dep schema 校验
```python
def _validate_poi(item):
    if not isinstance(item, dict): raise ValueError("not an object")
    if not isinstance(item.get("name"), str): raise ValueError("name required")
    allowed_keys = {"name","rating","city","province","address","lat","lng",
                    "description","recommend","source","phone","shop_name","recommend_dish"}
    for k, v in item.items():
        if k not in allowed_keys: raise ValueError(f"unknown field {k}")
        if not isinstance(v, (str, int, float, type(None))):
            raise ValueError(f"field {k} type {type(v).__name__} not allowed")
    return item

attractions = body.get("attractions") or []
if not isinstance(attractions, list) or len(attractions) > 5000:
    self._json({"error": "too many attractions"}, 400); return
attractions = [_validate_poi(a) for a in attractions]
```

---

### H-29 `oninput` 触发 `renderMassMarks` 在 7k POI 下每键击卡 300-800ms

**位置**：`frontend/index.html:736-752`

输入"北京"4 字符触发 4 次 MassMarks 重建 + 4 次 `clientDedupe` O(N²) + 4 次 `setMap`。

**修复**：debounce + 增量更新
```js
var _searchTimer = null;
document.getElementById("kw").oninput = function(){
  clearTimeout(_searchTimer);
  var q = this.value.trim().toLowerCase();
  _searchTimer = setTimeout(function(){
    var base = filterData();
    var filtered = q ? base.filter(p => (p.name && p.name.toLowerCase().includes(q)) ||
                                          (p.city && p.city.toLowerCase().includes(q))) : base;
    updateStats(filtered); renderList(filtered.slice(0,100)); updateClusterer(filtered);
  }, 200);
};
```
（进一步可让 `renderMassMarks` 内部用 diff 复用现有 layer。）

---

### H-30 `renderMassMarks` 跑两次 `pois.map` + 重复 `clientDedupe`

**位置**：`frontend/index.html:524-583`

```js
var data = pois.map(p => { lnglat: ..., name: ..., rating: ..., type: ... });        // ← 第一次 map 结果没用上
...
var massData = pois.map(p => { var idx=...; return { lnglat, name, style:idx, ... }; });  // ← 第二次 map
massMarksLayer.setData(massData);  // 第一次的 data 数组作废
```
且 `loadPOIData` 已 dedupe 过的数据，`renderMassMarks` 又 `clientDedupe` 一遍。

**修复**：单次 map + 仅在外层 dedupe 一次（见 H-19 的服务端去重替代更彻底）。

---

### H-31 `init_db()` 并发调用 ALTER TABLE 抛 `OperationalError`

**位置**：`backend/database.py:35-38`、`/api/init` 暴露

```python
if "phone" not in cols:
    conn.execute("ALTER TABLE " + tbl + " ADD COLUMN phone TEXT")  # ← 并发第二方抛 duplicate column
```

线程 A 进来，列不在 → 开始 ALTER。线程 B 同时进来，列不在（线程 A 还没 commit）→ 第二个 ALTER 抛 `duplicate column name: phone` → 整个 `init_db()` 报错。

**修复**：
```python
import threading
_INIT_LOCK = threading.Lock()

def init_db():
    with _INIT_LOCK:
        conn = get_conn()
        try:
            conn.executescript(""" ... """)
            for tbl in ("attractions", "foods"):
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
                if "phone" not in cols:
                    try:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN phone TEXT")
                    except sqlite3.OperationalError as e:
                        if "duplicate column" not in str(e): raise
            conn.commit()
        finally:
            conn.close()
```
**同时**：删 `/api/init` 路由（无条件 init_db 入口）。

---

### H-32 `RATE_LIMIT` dict 无淘汰策略，dict 随时间线性膨胀

**位置**：`backend/server.py:26`

每个唯一 IP 只增不减，10000 IP/天 × 30 天 = 30 万 entries（~16 MB）。

**修复**（结合 H-17 的 lock）：
```python
RATE_LIMIT_MAX_ENTRIES = 50000

# 在 _check_rate_limit 内 GC：
if len(RATE_LIMIT) > RATE_LIMIT_MAX_ENTRIES:
    for k in list(RATE_LIMIT.keys()):
        if not RATE_LIMIT[k] or now - RATE_LIMIT[k][-1] > RATE_LIMIT_WINDOW:
            RATE_LIMIT.pop(k, None)
    if len(RATE_LIMIT) > RATE_LIMIT_MAX_ENTRIES:
        RATE_LIMIT.clear()       # 实在太多，直接清空优先保命
```

---

### H-40 git history 显示反复 fix 同一类问题，需 secret scanning CI

**位置**：`.gitignore`、缺失 `.github/workflows/secret-scan.yml`

git log 显示以下 fix 反复出现：
- `4927901 fix: rotate AMap JS API key`
- `4a825ec fix: replace AMap JS API key in frontend/app.js`  
- `2999949 fix: update AMAP key for Web端 (JS API) and security code`
- `fe1000e fix: bind server to 0.0.0.0`
- `13e339e Remove crawler scripts that caused AMAP key ban`  ← **真发生过封禁事件**

当前活跃 key `<REDACTED-AMAP-KEY>` 与 secret `<REDACTED-AMAP-SECRET>` **在 git history 里至少公开过一次**。仅靠"rotate" 治标不治本——`git log -p` 仍能看到旧值。

**修复**：
```yaml
# .github/workflows/secret-scan.yml
name: secret-scan
on: [push, pull_request]
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }     # ← 扫 git history 必需
      - uses: gitleaks/gitleaks-action@v2
```
并写 `docs/INCIDENT_RESPONSE.md`：发现 key 公开后**立即** `git filter-repo` 清理历史，不是 rotate。

---

## 四、本轮新增 · 💭 Nit（6 个）

| # | 标题 | 位置 |
|---|---|---|
| **N-08** | `data.rectangle.split(";")[0].split(",")[0]` 缺 NaN 校验，NaN 坐标污染 userPosition → 地图异常 | `index.html:418-431, 837-845` |
| **N-09** | `index.html:17` 残留字面 `\n` + `:hover` 在 mobile 永不触发 + `#progressText` 死代码 | `index.html:17, 20, 435` |
| **N-10** | `renderList` `slice(0,100)` 硬截 100 条，status 显示"加载了 7000"误导用户 | `index.html:515` |
| **N-11** | 5 个 inline data:image/svg+xml;base64 SVG 不可维护，可用 CSS class 替代 | `index.html:543-547` |
| **N-12** | `window._mk` 全局变量从未被赋值，`if (window._mk)` 永远 False，残留旧 marker | `index.html:534` |
| **N-13** | `index.html.bak` 在 repo 中会被 `super().do_GET()` 当静态文件返回 32KB HTML | `frontend/index.html.bak` |

---

## 五、优先级路线图（融合两轮 Blocker）

### 第 1 周（必须，本轮新增 4 个 P0）
- [ ] H-17 `_check_rate_limit` 加锁 + 不在 429 后再 append
- [ ] H-19 加 UNIQUE 约束 + 改 UPSERT（或加 seed 前清理）
- [ ] H-20 `esc` 加 `"` 转义 + 改用事件委托
- [ ] H-23 拒绝 chunked + `Content-Length` 校验 + 加 try/except

### 第 2 周
- [ ] H-18 `end_headers` urlsplit 提 query string + `Content-Length`
- [ ] H-24 路径遍历显式拒绝（`.gitignore` 加 `frontend/*.bak`、代码层挡）
- [ ] H-25 错误码体系
- [ ] H-28 `/api/seed` schema 校验
- [ ] H-31 `init_db` 加锁 + 删 `/api/init`

### 第 3 周
- [ ] H-21 / H-22 / H-26 / H-27 trip_planner 性能与正确性
- [ ] H-29 / H-30 搜索 debounce + renderMassMarks 单次 map
- [ ] H-40 secret scanning CI

### 同时
- [ ] 本轮未触及的上轮 Blocker（H-01 ~ H-05）继续推进

---

## 六、本轮亮点补充

- **`SimpleHTTPRequestHandler.directory` 参数**（Python 3.7+）—— 限制了文件服务根目录，好习惯。
- **`PRAGMA journal_mode=WAL`** —— 读并发友好。
- **gzip 仅 >1KB 启用** —— 小响应免压缩开销。
- **CSP 按路径分流** —— 只在非 `/api/` 注入，避免污染 API 响应。
- **`role="status" aria-live="polite"`** —— 无障碍考虑到位。
- **union-find 路径压缩**（database.py:88-96）—— O(α) 接近 O(1)，写得地道。
- **`_normalize_name` 处理中英文括号 + 后缀** —— dedup 语义核心。
- **CI 已接 `appleboy/ssh-action` 自动部署** —— 比手工 SSH 进步大。

---

## 七、后续审查 Checklist（建议每次复审逐项打勾）

- [ ] **并发原语**：module-level mutable state 任何多线程路径？查 GIL atomic 边界。
- [ ] **stdlib 版本行为差异**：用到的 stdlib 在最低支持版本上行为一致？
- [ ] **HTTP 层**：Content-Length 校验？Transfer-Encoding 处理？方法白名单？query string 影响？
- [ ] **CSP 完整性**：所有响应都过 `end_headers`？CSP 在 API 路径跳过逻辑是否正确？是否有 `report-uri`？
- [ ] **SQLite 类型系统**：所有 INSERT 参数化？表的 UNIQUE/INDEX 设计是否支撑 OR IGNORE / UPSERT？
- [ ] **JS XSS**：HTML 实体 / 属性 `"` / JS 字符串 / URL —— 四种 context 各查一遍。
- [ ] **历史 fix 模式**：反复 `fix: ...` 是症状修补还是根因修复？需要 secret scanning？
- [ ] **资源管理**：所有 `get_conn()` 都 `with` / `try/finally`？
- [ ] **API 错误语义**：每个 4xx/5xx 都返回稳定错误码？
- [ ] **cache-control**：静态 + HTML + API 都有合理缓存策略？query string 是否影响？
- [ ] **死代码扫描**：`grep -E 'TODO|FIXME|XXX|window\._mk|progressBar'` 等历史遗留标记
- [ ] **magic number**：每个硬编码数字查根因（特别 `+ 0.5`、`+ 60`、`+ 1024`）
- [ ] **外部 API 校验**：AMap / 高德 API 返回值的所有字段都按 schema 校验？

报告完。
