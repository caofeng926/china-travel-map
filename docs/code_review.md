# 中国旅游地图项目 - 代码审查报告

> 审查范围：`backend/*.py`（5 个）、`frontend/index.html`、`frontend/app.js`、`deploy/*`（2 个）、`.github/workflows/*`、配置文件
> 审查时间：2026-07-26
> 审查人：Code Reviewer Agent
> 总代码量：~7,063 行

---

## 一、整体印象

项目是一个**纯 Python 标准库 + 原生 JS** 的轻量级 Web 应用，覆盖了路线规划、POI 查询、数据导入、地图展示等完整闭环，**功能完成度较高、零三方依赖、易部署** 是其最大亮点。

但作为生产代码仍存在一系列**安全漏洞、性能瓶颈、可维护性短板**。尤其是 `/api/deploy` 远程 shell 执行端点、CORS 兜底逻辑过宽、客户端硬编码 AMap Key、以及高德返回 7000+ POI 时无差别全量查询+O(N²) 去重等问题，必须在投产前修掉。

| 维度 | 评分 | 关键问题 |
|---|---|---|
| 功能完整性 | ⭐⭐⭐⭐⭐ | 数据齐全，闭环可用 |
| 安全性 | ⭐⭐ | ⚠️ 多处高危（CORS、`/api/deploy`、Token 走明文、AMap Key 硬编码） |
| 性能 | ⭐⭐ | ⚠️ 全表扫描 + 双重 O(N²) 去重 |
| 可维护性 | ⭐⭐⭐ | ⚠️ `seed.py` 5500 行硬编码、连接未用 `with` |
| 工程规范 | ⭐⭐ | ⚠️ bare except、unicode 转义、缺类型标注、缺 logging |
| 可测试性 | ⭐⭐ | ⚠️ 5 个测试覆盖，连 trip_planner 都没测 |

---

## 二、问题汇总（按严重程度）

| 编号 | 严重度 | 模块 | 简述 |
|---|---|---|---|
| **H-01** | 🔴 Blocker | `server.py` | `/api/deploy` 远程命令执行 + Token 明文 HTTP |
| **H-02** | 🔴 Blocker | `server.py` | CORS 兜底返回 `*`，导致跨域滥用 |
| **H-03** | 🔴 Blocker | `frontend/*` | AMap Web 服务 Key 硬编码在客户端，潜在盗刷 |
| **H-04** | 🔴 Blocker | `server.py` | Token 通过 HTTP Header 明文传输，未强制 HTTPS |
| **H-05** | 🔴 Blocker | `database.py` | `/api/pois` 无差别返回全部数据 + O(N²) 去重（无缓存） |
| H-06 | 🟡 Suggestion | `database.py` | 连接未用上下文管理器，异常会泄漏 |
| H-07 | 🟡 Suggestion | `server.py` | 全部用 `try/except Exception` + `print`，吞错且无日志 |
| H-08 | 🟡 Suggestion | `seed.py` | 5,531 行硬编码 POI 字典，污染版本控制 diff |
| H-09 | 🟡 Suggestion | `test_api.py` | 测试覆盖率严重不足，无 trip_planner/API 边界用例 |
| H-10 | 🟡 Suggestion | `frontend/*` | 上万字符串拼接构建 DOM，未使用 DocumentFragment/innerHTML 转义面不足 |
| H-11 | 🟡 Suggestion | `frontend/*` | Unicode 转义符 `\u4e2d\u6587`，可读性极差 |
| H-12 | 🟡 Suggestion | `server.py` | `init_db()` 在 `GET /api/init` 中被无鉴权触发，可被任意调用 |
| H-13 | 🟡 Suggestion | `frontend/app.js` | 已淘汰的旧版本 JS 仍保留，且与 index.html 实现重叠 |
| H-14 | 🟡 Suggestion | `database.py` | `init_db` 用字符串拼接 `+ tbl +`，虽硬编码但风格不佳 |
| H-15 | 🟡 Suggestion | `nginx.conf` | CSP/安全头在 Python 层和 Nginx 层重复，可能冲突 |
| H-16 | 🟡 Suggestion | 全局 | 缺类型注解 / 缺 logging / 缺 API 文档 |
| N-01 | 💭 Nit | `database.py` | Magic number 散落（`timeout=10`、`15` km 搜索半径） |
| N-02 | 💭 Nit | `seed.py` | 大量 `"address": ""` 空字段冗余 |
| N-03 | 💭 Nit | `.gitignore` | 包含了 30+ 历史开发脚本 glob，未及时清理 |
| N-04 | 💭 Nit | `frontend/index.html` | 包含 `<div>\n` 注释残留（行 17 等） |
| N-05 | 💭 Nit | `build_full_data.py` | 文件头被截断（`init_data()` 函数定义缺失） |
| N-06 | 💭 Nit | `nginx.conf` | `server_name vps5865.top` 仍使用占位域名 |
| N-07 | 💭 Nit | `requirements.txt` | 仅 1 行注释，缺少真实依赖说明 |

---

## 三、🔴 Blocker 详细分析

### H-01 /api/deploy 远程命令执行（**极高危**）

**位置**：`backend/server.py:85-102`

```python
elif self.path == "/api/deploy":
    token = self.headers.get("Authorization", "").replace("Bearer ", "")
    if not SEED_TOKEN or token != SEED_TOKEN:
        self._json({"error": "unauthorized"}, 401)
        return
    import subprocess as _sp
    cmds = []
    cmds.append("cd /opt/china-travel-map && git pull 2>&1 || true")
    cmds.append("systemctl restart china-travel-map 2>&1 || nginx -s reload 2>&1 || true")
    results = {}
    for i, cmd in enumerate(cmds):
        try:
            r = _sp.check_output(cmd, shell=True, timeout=60, stderr=_sp.STDOUT)
```

**风险**：
- 任何拿到 `SEED_TOKEN` 的人都可直接让你的服务器**拉代码 + 重启**，构成完整的供应链接管。
- 即使 `pkill`/重启本身是良性的，**它向 Web 暴露了一个 RCE 跳板**——若未来有人在 `cmds` 列表里加入任何拼接用户输入的命令，即是灾难。
- `shell=True` + 60s timeout 让任何被拼进去的字符串都能拿到完整 shell。

**优化方案**（优先级最高）：
1. **立刻删除此端点**，将部署改为 CI 自动触发（GitHub Actions 你已经接好了，**不需要再开 Web 接口**）。
2. 如必须保留：
   - 接收的不是命令字符串，而是固定分支名（白名单）
   - 改 `subprocess.run(["/opt/china-travel-map/deploy/deploy_server.sh"], shell=False)`
   - 强制要求 HTTPS + IP 白名单
   - 增加一次性 nonce + 时间窗（防重放）

```python
# 推荐替换
ALLOWED_DEPLOY_IPS = {"127.0.0.1"}  # 仅本机/反代
cmd_script = "/opt/china-travel-map/deploy/deploy_server.sh"
r = subprocess.run([cmd_script], shell=False, capture_output=True, timeout=300)
```

---

### H-02 CORS 兜底返回 `*`（**跨域滥用**）

**位置**：`backend/server.py:107-114`

```python
def _get_allowed_origin(self):
    origin = self.headers.get("Origin", "")
    if not origin:                       # ← 当没有 Origin 头时
        return "*"                       # ← 直接放通！
    for allowed in ALLOWED_ORIGINS:
        ...
```

**风险**：
- 同源请求**没有 Origin 头**（curl、Postman、服务端到服务端调用），会拿到 `*`，响应通过 `Access-Control-Allow-Origin: *` 返回。
- 即使前端利用 `withCredentials` 已被浏览器拒绝（`*` 拒绝带 cookie），但**任意第三方网站**都能发请求消耗你的接口、爬你的 7000+ POI、触发 `/api/seed` 写入（虽然要 token，但被刷也是有耗损）。
- 此外 `ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "").split(",")` 当 env 为空时**默认用 `["http://localhost:8765"]`**，但 `.split(",")` 在空字符串上返回 `[""]`，再 `or ["http://localhost:8765"]` 是冗余逻辑。

**优化方案**：
```python
def _get_allowed_origin(self):
    origin = (self.headers.get("Origin") or "").strip()
    if not origin:
        return ""  # 没有 Origin 头时不要返回 *
    return origin if origin in [a.strip() for a in ALLOWED_ORIGINS if a.strip()] else ""
```

调用方已经做了 `if origin:` 判断，删掉那段兜底逻辑即可。

---

### H-03 AMap Web 服务 Key 暴露在前端

**位置**：`frontend/index.html:211`、`frontend/app.js:5`、`frontend/app.js:7`、`.env.example`

```js
var AMAP_KEY = "<REDACTED-AMAP-KEY>"  // literal key removed from version control after INCIDENT_RESPONSE;      // 已在 Git 提交
var AMAP_SECRET = "<REDACTED-AMAP-SECRET>";   // 已泄露
window._AMapSecurityConfig = { securityJsCode: AMAP_SECRET };
```

**风险**：
- 这是**高德 Web 端 JS API 的 key + 数字签名**，被设计成可公开放前端使用的——但它有**日调用配额**，任何人可扒走 key 去恶意刷你的额度。
- 出现在最近的 commit `fix: replace AMap JS API key in frontend/app.js`，说明你已经在轮换，但**轮换是手动且不可审计的**。
- 同时 `.env.example`（提交进 git 的）只画了 Web 服务 key 占位，未画明 JS key 从哪里来。

**优化方案**：
1. 在 `.env.example` 写明：
   ```
   # AMap JS API Key (front-end, public by design but rotate if abused)
   AMAP_JS_KEY=...
   AMAP_JS_SECURITY_CODE=...
   ```
2. 加**前端域名白名单 + 每日 QPS 限制**（在 https://console.amap.com 后台配）。
3. 在前端加 abuse 检测：如果 `console.log` 莫名刷日志/异常 curl，立刻在后台拉黑 IP。
4. 长期方案：把签名生成放到自己后端代理。

---

### H-04 Token 通过明文 HTTP 传输

**位置**：`deploy/deploy_server.sh:48-50`、`.github/workflows/deploy.yml:36-52`、`server.py:19`

```python
HOST, PORT = "0.0.0.0", 8765   # 监听 0.0.0.0，且默认 HTTP（无 TLS）
```

**风险**：
- 即便 Token 本身强（`openssl rand -hex 32`），调用 `Authorization: Bearer xxx` 在 HTTP 明文下就是裸奔。
- deploy.sh 只配了 `https://$DOMAIN`，但**裸跑 `python3 server.py` 时无 TLS**，本地或内网任何抓包者都看得到 Token。

**优化方案**：
- 强制要求由 Nginx 反代（见 `deploy/nginx.conf`），**关闭 8765 的公网监听**（firewall / `bind 127.0.0.1`）。
- 把 `HOST` 默认值改为 `127.0.0.1`，并把注释写明 "production MUST go through Nginx with TLS"。

```python
# 生产警告
HOST, PORT = "127.0.0.1", int(os.environ.get("PORT", "8765"))
if HOST == "0.0.0.0":
    print("WARN: binding 0.0.0.0 is unsafe without TLS. Prefer 127.0.0.1 + Nginx.")
```

---

### H-05 全表查询 + 双重 O(N²) 去重（**性能致命**）

**位置**：`backend/database.py:211-279`、`frontend/app.js:359-410`

服务端：
```python
# search_pois 跑一遍全表 → 返回所有行 → _dedup_attractions 又用 O(N²) 同名/坐标聚类
if not keyword and not center_lat:
    results[:] = _dedup_attractions(results)
```

客户端：
```js
allPois = clientDedupe(allPois);   // 再做一遍 O(N²) 同名归一
```

**问题**：
- `_dedup_attractions` 是 O(N²)：每个 i 与后面每个 j 比较（lines 100-143），7000 条要 4900 万次比较、每次还含 haversine。
- 客户端又重复一次。
- 没有缓存：每次 `GET /api/pois?type=food` 又做一遍。
- `keyword` 搜索避开了 dedup（出于兼容），但 `page_size=4000` 直接拉了所有数据全内存处理。

**优化方案**（短期 → 长期）：
1. **立刻**：
   - 给 dedup 结果加 LRU 缓存 `@functools.lru_cache(maxsize=4)` 或者 `(center_lat is None and keyword is None)` 时缓存。
   - 给 `clientDedupe` 加同样的缓存。
2. **短期**：
   - `page_size` 默认 200 改为 100，前端按需 lazy fetch。
3. **中期**：
   - 服务端 dedup 改 batched/Union-Find-by-bucket（先按 city 拆分再并查集）。
4. **长期**：
   - 把 dedup 放进 `seed.py` 导入时一次性完成，**存储的就是去重后的"官方"数据**——接口本身不需要每次去重。

```python
@functools.lru_cache(maxsize=8)
def _get_cached_pois(page_size, type_filter, compact):
    # ... 完整逻辑
    return {"total": ..., "results": ...}
```

---

## 四、🟡 Suggestion 详细分析

### H-06 SQLite 连接未用上下文管理器

**位置**：`database.py` 全文件（6 处函数均 `conn = get_conn(); ... conn.close()`）

**问题**：异常路径（如 `json.loads` 解析失败、`socket.timeout`）会导致连接泄漏。WAL 模式下短时影响小，长跑会达到 `SQLITE_BUSY`。

**修复**：
```python
from contextlib import contextmanager

@contextmanager
def db_conn():
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()

def search_pois(...):
    with db_conn() as conn:
        ...
```

---

### H-07 bare `except` + `print`，完全无日志

**位置**：`server.py:11,16`, `trip_planner.py:25,53,87`, `app.js` 多处

```python
try: return float(v) if v is not None and v != "" else d
except: return d                  # bare except 吞掉一切
except Exception as e:
    print(f"Driving route error: {e}")   # print ≠ logging
```

**修复**：
```python
import logging
log = logging.getLogger(__name__)
try:
    ...
except (ValueError, TypeError) as e:
    log.warning("geocode failed for %s: %s", address, e)
```

`logging` 配置放到环境变量 `LOG_LEVEL`。

---

### H-08 `seed.py` 5,531 行硬编码字典

**位置**：`backend/seed.py`

**问题**：
- 5531 行 Python 数组，每次新增一个景点都要 PR 一坨 dict，diff 难读。
- 没有数据与代码分离，热加载没法做。

**修复**：
1. 把 POI 数据搬到 `backend/data/seed_data.json`（已经存在 `data/china_travel.db`，结构顺）：
   ```json
   [
     {"name": "宝塔山", "city": "延安", "province": "陕西", "lat": 36.597, "lng": 109.493, ...}
   ]
   ```
2. `seed.py` 缩成：
   ```python
   def main():
       init_db()
       items = json.load(open(BASE / "data" / "seed_data.json"))
       insert_attractions(items)
   ```
3. 进一步可分文件 `data/seed/{province}.json` 让 diff 仅影响本省。
4. 加 `Makefile` 目标 `make seed` 触发。

---

### H-09 测试覆盖严重不足

**位置**：`backend/test_api.py`（仅 5 个用例）

**问题**：
- `trip_planner.plan_trip` 完全没覆盖。
- `server.py` 全部路由完全没覆盖（无 HTTP 层测试）。
- `/api/seed` 的鉴权/限流/边界没有用例。
- SQL 注入测试没有。

**修复**：补充以下最小测试集

```python
class TestSecurity(unittest.TestCase):
    def test_seed_requires_token(self): ...
    def test_seed_too_large_body_rejected(self): ...
    def test_sql_injection_in_keyword(self):
        # 注入到 keyword 里，验证不报错且返回空
        r = database.search_pois(keyword="'; DROP TABLE attractions; --")
        self.assertEqual(r["total"], 0)
    def test_rate_limit(self): ...

class TestTripPlanner(unittest.TestCase):
    @mock.patch("trip_planner.geocode")
    def test_plan_trip_driving(self, mock_geo): ...
    @mock.patch("trip_planner.geocode", return_value=(None, None, ""))
    def test_plan_trip_invalid_address(self, mock_geo): ...
```

集成测试可以用 `unittest` 内置 `subprocess`，另加 `pytest` + `httpx` 测 HTTP 层。

---

### H-10 DOM 拼接 + 转义不全面

**位置**：`app.js:565-575`、`index.html:562-574`

```js
html+='<div class="item" onclick="flyTo('+p.lat+","+p.lng+')">';
html+='<div class="info"><div class="name">'+esc(p.name)+'</div><div class="sub">'+esc(p.city||"")+'</div></div>';
html+='<div class="tag '+cls+'">'+tag+'</div></div>';
```

**问题**：
- `p.name` 经过了 `esc()`，但 `tag` 没经过（虽然 `tag` 是 `p.rating` 替换而来，rating 字段在数据库是受控的值，但理论上仍是隐患）。
- 列表渲染用 `arr.slice(0,100).forEach` × 字符串拼接，每次 `updateClusterer` 都重新生成 100 个 onclick handler——不必要，可改成 event delegation。
- 大数据量（4000+ 条）一次性 `innerHTML = ...` 阻塞主线程。

**修复**：统一使用 `esc()` + 文档片段：
```js
const frag = document.createDocumentFragment();
for (const p of show) {
  const div = document.createElement("div");
  div.className = "item";
  div.onclick = () => flyTo(p.lat, p.lng);
  div.innerHTML = `<div class="dot ${cls}"></div>...`;
  frag.appendChild(div);
}
listEl.replaceChildren(frag);
```

---

### H-11 全项目 Unicode `\uXXXX` 转义

**位置**：`server.py:50,51,84,85,144,154,165,166`，`trip_planner.py:50,51,84,85,166,168,174`，前端 JS 大量 `\u4e2d\u6587` 字符串、SVG 中文标签

**问题**：
- 已是不可读状态。`{dur//3600}\u5c0f\u65f6{(dur%3600)//60}\u5206` = `f"{dur//3600}小时{(dur%3600)//60}分"`。
- 早期为了避免 Windows GBK 编码损坏而转义——但 Python 3 源文件默认 UTF-8，**已经没有这个理由**。
- 提交 diff 中真中文比 `\u` 转义更易 review。

**修复**：
1. 设 `# -*- coding: utf-8 -*-`（已经默认）或者文件第一行 `# coding: utf-8`。
2. 在 `.editorconfig` 加 `charset = utf-8`，保证团队一致。
3. 用 `grep -n '\\\\u[0-9a-f]\{4\}' backend/*.py` 替换为字面中文。

---

### H-12 `/api/init` 无鉴权即可 init_db

**位置**：`server.py:37-38`

```python
if self.path == "/api/init":
    init_db(); self._json({"ok":True})
```

**问题**：init_db 是幂等的，无大碍，但 `create table` 与 ALTER 在并发下可能失败；应移除此端点或在 `init_db()` 内部加锁。

**修复**：直接删除该路由，初始化只在启动时做。

---

### H-13 `frontend/app.js` 是历史遗留

**位置**：`frontend/app.js`（208 行）

**问题**：
- 与 `index.html` 实现高度重叠（都是 same Google-like UI），但功能更新主要在 `index.html`。
- 文件中还保留一个错误的 `var AMAP_KEY = '...'`，上次 commit `fix: replace AMap JS API key in frontend/app.js` 就在轮换 key——意味着这是事故后才打补丁，关键证据它应当**直接删除**。

**修复**：`rm frontend/app.js` 并移除 `.gitignore`/`docs` 中的引用。

---

### H-14 `init_db` 字符串拼接虽硬编码但风格不佳

**位置**：`database.py:35-38`

```python
for tbl in ("attractions", "foods"):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(" + tbl + ")").fetchall()}
    if "phone" not in cols:
        conn.execute("ALTER TABLE " + tbl + " ADD COLUMN phone TEXT")
```

**问题**：tbl 是硬编码的，目前没风险；但用 `?` 参数化更稳妥且风格统一。`PRAGMA` 不接受参数（SQLite 限制），可用 `sqlite3.Connection.execute(f"...{tbl}...")` 或者通过 `sqlite_master` 查询。

**修复**：保持现状但在注释里标明硬编码列表的取值范围。

---

### H-15 Nginx 与 Python 双重安全头

**位置**：`nginx.conf:27-31` 与 `server.py:140-150`

两边都设置了 CSP/X-Frame-Options。**最终生效的是 Nginx**（代理后响应经过 Nginx 写出）。Python 这层只在直接访问 8765 时生效。问题不大，但**两边策略必须同步**，否则出 bug。

**修复**：提取到 `.env` 或配置中心；CI 加个 lint 检查头字段一致。

---

### H-16 工程基础缺位（类型、日志、文档）

**影响**：可维护性。

**修复清单**：
- 引入 `mypy` + `pyright` 检查类型注解
- 引入 `ruff`/`flake8` + `black`/`ruff format`
- 用 `logging` 替换 `print`
- 写 `docs/API.md`：每个端点的入参、返回、错误码、限流策略
- 写 `docs/DEPLOY.md`：含 `--no-input` 的 unattended 模式、回滚策略
- 在 CI `test` job 加 lint：`ruff check .` + `mypy backend/`

---

## 五、💭 Nit（低优先级优化）

| 编号 | 建议 |
|---|---|
| N-01 | 把 `SEARCH_RADIUS=15`, `RATE_LIMIT_MAX=60`, `MAX_BODY_SIZE` 提到 `config.py`，可通过 env 覆盖 |
| N-02 | `seed.py` 里 `"address": ""` 与 `"recommend": ""` 占位大量重复，可用 `dict(defaultdict(str))` factory |
| N-03 | `.gitignore` 看起来是逐步累加的——许多 `check_*.py`、`fix_*.py`、`merge_*.py` glob 是临时脚本，没必要进 `.gitignore`（已经删了的就不要 ignore 了）。整理后 `wc -l .gitignore` 从 110 降到 ~30 |
| N-04 | `index.html:17` 注释里有个 `\n` 残留在 HTML 属性后，浏览器会渲染成空白 |
| N-05 | `build_full_data.py` 文件头被截断，函数 `init_data()` 没定义——若已弃用，直接删除 |
| N-06 | `nginx.conf` 里 `server_name vps5865.top` 是占位，应当提醒 `sed -i 's/vps5865.top/$REAL_DOMAIN/'` |
| N-07 | `requirements.txt` 只有 1 行——改写为"零外部依赖"声明，避免误装包 |

---

## 六、性能基准（建议补）

请在修复后跑一次：

```bash
# 1. 全表查询基准
time curl "http://localhost:8765/api/pois?page_size=5000"

# 2. 限流压测
ab -n 200 -c 50 "http://localhost:8765/api/health"

# 3. 路由规划最坏路径
time curl "http://localhost:8765/api/plan_trip?origin=北京&dest=三亚&mode=transit"
```

把结果填入 `docs/perf_baseline.md`，作为回归基线。

---

## 七、修复优先级与路线图

### 第 1 周（必须）
- [ ] H-01 移除 `/api/deploy`（改 CI 自动）或严格白名单
- [ ] H-02 修复 CORS 兜底
- [ ] H-04 强制 `127.0.0.1` 绑定 + 文档警告
- [ ] H-12 删除 `/api/init`

### 第 2–3 周（强烈建议）
- [ ] H-05 dedup 加缓存，前端 lazy-fetch
- [ ] H-08 `seed.py` 拆分为 JSON
- [ ] H-13 删除 `app.js`
- [ ] H-11 还原 `\uXXXX` 为字面中文
- [ ] 测试补到 30+ 用例

### 第 4 周起（持续）
- [ ] 接入 `ruff` + `mypy` + `black`
- [ ] 引入 `logging` + structured JSON 日志
- [ ] API/部署文档
- [ ] CI lint 步骤
- [ ] H-14/H-15/H-16 清理

---

## 八、亮点（值得保留的代码片段）

- **`_dedup_attractions` 的并查集实现**（`database.py:87-143`）：递归路径压缩写得地道，O(α) 复杂度。
- **CSP 配置按路径分流**（`server.py:140-150`）：只在非 `/api/` 路径下注入 CSP，避免污染 API 响应。
- **服务端去重 + 客户端二次去重双保险**（"safety net"）：是一种纵深防御思路（虽然当前性能代价大，但模型正确）。
- **`/api/health` 路由**：便于 Nginx/uptime 监控接入。
- **`gzip` 压缩选择器**（`server.py:153-176`）：仅当响应 >1KB 才压缩，避免小响应的压缩开销。
- **数据库 `WAL` 模式**（`database.py:8`）：并发读写能力好，正确选择。
- **`uuid` 风格事件委托**（`index.html:279-286`）：相比每个 marker 绑 onclick 高效。
- **`role="status" aria-live="polite"`**（`index.html:159`）：无障碍考虑到位。

---

## 九、审查结论

| | 修复前 | 修复目标 |
|---|---|---|
| **可投产性** | ❌ Blocker 级别风险未消除 | 移除 `/api/deploy`、修复 CORS/HTTPS 后**可生产** |
| **可扩展性** | ⭐⭐ 5k 行硬编码是天花板 | JSON 化 + dedup 缓存后可承载 50k+ |
| **可维护性** | ⭐⭐⭐ 1 人维护可行 | 加入 lint/type/logging 后团队 5 人也无压力 |

---

报告完。
