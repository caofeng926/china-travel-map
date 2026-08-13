"""China Travel Map - HTTP API Server"""
import http.server, json, os, sys, gzip, io, time, hashlib, threading, re
from urllib.parse import urlparse, parse_qs, urlsplit
from functools import wraps

# H-25: stable error codes so clients + log aggregators can branch on `code`
# without parsing free-form messages.
ERROR_CODES = {
    "bad_request":        {"status": 400, "message": "请求格式错误"},
    "unauthorized":       {"status": 401, "message": "未授权"},
    "not_found":          {"status": 404, "message": "未找到"},
    "chunked_unsupported":{"status": 411, "message": "不支持 chunked 编码"},
    "payload_too_large":  {"status": 413, "message": "请求体过大"},
    "rate_limited":       {"status": 429, "message": "请求过于频繁"},
    "internal_error":     {"status": 500, "message": "服务器内部错误"},
}
def _validate_poi(item, allowed):
    if not isinstance(item, dict):
        raise ValueError("not an object")
    for k, v in item.items():
        if k not in allowed:
            raise ValueError("unknown field " + str(k))
        if v is not None and not isinstance(v, (str, int, float)):
            raise ValueError("field " + str(k) + " has unsupported type " + type(v).__name__)
    if not isinstance(item.get("name"), str) or not item["name"]:
        raise ValueError("name required")
    return item

_ATTRACTION_KEYS = frozenset({"name","rating","city","province","address","lat","lng",
                              "description","recommend","source","phone"})
_FOOD_KEYS = frozenset({"name","city","province","lat","lng","description","address",
                        "shop_name","recommend_dish","phone","source"})


sys.path.insert(0, os.path.dirname(__file__))
from database import init_db, search_pois, get_stats, insert_attractions, insert_foods
from trip_planner import plan_trip

def _sf(v, d=None):
    """Safe float conversion, returns d on failure"""
    try: return float(v) if v is not None and v != "" else d
    except: return d

def _si(v, d=None):
    """Safe int conversion, returns d on failure"""
    try: return int(v) if v is not None and v != "" else d
    except: return d

HOST, PORT = "0.0.0.0", 8765
FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend")

# Security config
MAX_BODY_SIZE = 1024 * 1024  # 1MB max POST body
SEED_TOKEN = os.environ.get("SEED_TOKEN", "")  # Set this for /api/seed access
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "").split(",") or ["http://localhost:8765"]
RATE_LIMIT = {}            # {ip: [timestamp, ...]}
RATE_LIMIT_LOCK = threading.Lock()  # H-17: guards all RATE_LIMIT mutation
RATE_LIMIT_WINDOW = 60     # seconds
RATE_LIMIT_MAX = 60        # max requests per window
RATE_LIMIT_MAX_ENTRIES = 50000  # H-32: cap dict size to bound memory

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=FRONTEND, **kw)

    def do_GET(self):
        if not self._check_rate_limit():
            return
        # H-24: refuse path traversal up front, even on Python <3.11 where
        # SimpleHTTPRequestHandler.translate_path still allows "..".
        raw_path = urlparse(self.path).path
        if ".." in raw_path.split("/") or raw_path.startswith("//") or not raw_path.startswith("/"):
            self._err("bad_request"); return
        if self.path == "/api/init":
            # H-31: init_db mutates schema; gate it behind SEED_TOKEN so an
            # anonymous visitor can't keep re-running schema migrations.
            token = self.headers.get("Authorization", "").replace("Bearer ", "")
            if not SEED_TOKEN or token != SEED_TOKEN:
                self._err("unauthorized"); return
            init_db(); self._json({"ok": True})
        elif self.path == "/api/stats":
            self._json(get_stats())
        elif self.path.startswith("/api/pois"):
            p = parse_qs(urlparse(self.path).query)
            def g(k, d=None): return p.get(k, [d])[0]
            self._json(search_pois(
                compact = g("compact", "1") == "1",
                center_lat=_sf(g("lat")),
                center_lng=_sf(g("lng")),
                radius_km=_sf(g("radius"), 500),
                rating=g("rating"), type_filter=g("type"),
                keyword=g("keyword"), province=g("province"), city=g("city"),
                page=max(1, _si(g("page"), 1) or 1), page_size=min(_si(g("page_size"), 2000) or 2000, 10000)
            ))
        elif self.path.startswith("/api/plan_trip"):
            p = parse_qs(urlparse(self.path).query)
            def g(k, d=None): return p.get(k, [d])[0]
            self._json(plan_trip(
                origin_name=g("origin", ""),
                dest_name=g("dest", ""),
                mode=g("mode", "driving")
            ))
        elif self.path == "/api/health":
            self._json({"status":"ok","service":"china-travel-map"})
        elif self.path == "/api/config.js":
            # H-NEW: serve the AMap JS key + security code from env, never from
            # source. Frontend loads this <script> before reading AMAP_KEY.
            import json as _json
            cfg = _json.dumps({
                "amap_key":    os.environ.get("AMAP_KEY", ""),
                "amap_secret": os.environ.get("AMAP_SECRET", ""),
            })
            body = ("window.AMAP_CONFIG = " + cfg + ";").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        elif self.path == "/api/ip_locate":
            # Server-side IP geolocation proxy. The frontend hits this same-
            # origin endpoint to dodge CORS / browser-side network blocks
            # against public IP APIs (e.g. ipwho.is from inside China).
            # We try ipinfo first (returns a clean "lat,lng" string), then
            # fall back to ipwho.is. Optional AMap /v3/ip attempt last.
            import json as _json, urllib.request as _ur
            # Client IP: trust the first hop in X-Forwarded-For when the
            # request is fronted by nginx; otherwise fall back to the socket
            # peer. Trimmed to avoid whitespace / extra commas.
            xff = self.headers.get("X-Forwarded-For", "") or ""
            client_ip = xff.split(",")[0].strip() if xff else self.client_address[0]
            ua = {"User-Agent": "china-travel-map/1.0"}
            # --- ipinfo.io ---
            try:
                url = ("https://ipinfo.io/" + client_ip + "/json") if client_ip else "https://ipinfo.io/json"
                req = _ur.Request(url, headers=ua)
                with _ur.urlopen(req, timeout=4) as r:
                    data = _json.loads(r.read().decode("utf-8", "replace"))
                if "loc" in data and "," in data["loc"]:
                    lat_s, lng_s = data["loc"].split(",", 1)
                    self._json({
                        "ok": True,
                        "source": "ipinfo",
                        "ip": data.get("ip", client_ip),
                        "lat": float(lat_s),
                        "lng": float(lng_s),
                        "country": data.get("country", ""),
                        "region":  data.get("region",  ""),
                        "city":    data.get("city",    ""),
                    })
                    return
            except Exception as _e:
                print("ipinfo failed:", _e, file=sys.stderr)
            # --- ipwho.is ---
            try:
                url = ("https://ipwho.is/" + client_ip) if client_ip else "https://ipwho.is/"
                req = _ur.Request(url, headers=ua)
                with _ur.urlopen(req, timeout=4) as r:
                    data = _json.loads(r.read().decode("utf-8", "replace"))
                if data.get("success") is not False and isinstance(data.get("latitude"), (int, float)):
                    self._json({
                        "ok": True,
                        "source": "ipwho.is",
                        "ip": data.get("ip", client_ip),
                        "lat": float(data["latitude"]),
                        "lng": float(data["longitude"]),
                        "country": data.get("country", ""),
                        "region":  data.get("region",  ""),
                        "city":    data.get("city",    ""),
                    })
                    return
            except Exception as _e:
                print("ipwho.is failed:", _e, file=sys.stderr)
            self._json({"ok": False, "error": "all_ip_apis_failed"}, status=503)
            return
        else:
            super().do_GET()

    def do_POST(self):
        if not self._check_rate_limit():
            return
        if self.path == "/api/seed":
            # H-23: refuse chunked (would smear across the next request),
            # validate Content-Length, wrap JSON parsing in try/except.
            te = (self.headers.get("Transfer-Encoding") or "").lower()
            if "chunked" in te:
                self._err("chunked_unsupported"); return
            try:
                cl = int(self.headers.get("Content-Length") or "0")
            except (TypeError, ValueError):
                self._err("bad_request"); return
            if cl < 0 or cl > MAX_BODY_SIZE:
                self._err("payload_too_large"); return

            token = self.headers.get("Authorization", "").replace("Bearer ", "")
            if not SEED_TOKEN or token != SEED_TOKEN:
                self._err("unauthorized"); return

            try:
                body = json.loads(self.rfile.read(cl))
            except (json.JSONDecodeError, ValueError):
                self._err("bad_request"); return
            # H-28: validate body shape before reaching SQLite.
            try:
                attrs = [_validate_poi(a, _ATTRACTION_KEYS) for a in (body.get("attractions") or [])]
                foods = [_validate_poi(f, _FOOD_KEYS) for f in (body.get("foods") or [])]
            except ValueError as e:
                self._json({"error": "invalid item", "code": "bad_request", "detail": str(e)}, 400)
                return
            if len(attrs) > 5000 or len(foods) > 5000:
                self._err("payload_too_large"); return
            insert_attractions(attrs)
            insert_foods(foods)
            self._json({"ok": True, "imported": len(attrs) + len(foods)})

        elif self.path == "/api/deploy":
            # Deploy endpoint - pull latest code and restart
            te = (self.headers.get("Transfer-Encoding") or "").lower()
            if "chunked" in te:
                self._err("chunked_unsupported"); return
            try:
                cl = int(self.headers.get("Content-Length") or "0")
            except (TypeError, ValueError):
                self._err("bad_request"); return
            if cl < 0 or cl > MAX_BODY_SIZE:
                self._err("payload_too_large"); return
            try:
                _sp_dummy = json.loads(self.rfile.read(cl) or b"{}")
            except (json.JSONDecodeError, ValueError):
                self._err("bad_request"); return

            token = self.headers.get("Authorization", "").replace("Bearer ", "")
            if not SEED_TOKEN or token != SEED_TOKEN:
                self._err("unauthorized"); return
            import subprocess as _sp
            cmds = []
            cmds.append("cd /opt/china-travel-map && git pull 2>&1 || true")
            cmds.append("systemctl restart china-travel-map 2>&1 || nginx -s reload 2>&1 || true")
            results = {}
            for i, cmd in enumerate(cmds):
                try:
                    r = _sp.check_output(cmd, shell=True, timeout=60, stderr=_sp.STDOUT)
                    results[f"cmd{i}"] = r.decode("utf-8", "replace")
                except Exception as e:
                    results[f"cmd{i}_error"] = str(e)
            self._json({"ok": True, "results": results})

        else:
            self._err("not_found")

    def _get_allowed_origin(self):
        origin = self.headers.get("Origin", "")
        if not origin:
            return "*"
        for allowed in ALLOWED_ORIGINS:
            if allowed and allowed.strip() and origin == allowed.strip():
                return origin
        return ""

    def _check_rate_limit(self):
        # H-17: ThreadingHTTPServer dispatches each request on its own thread;
        # GIL does NOT make dict mutation atomic across statements, so the old
        # code lost counts and could permanently ban an IP after one burst
        # (a 1-second 60-req burst left the entry appended for the lifetime of
        # the window). Hold a single lock for the whole critical section.
        # H-32: also GC empty/stale entries when the dict grows past the cap.
        ip = self.headers.get("X-Real-IP", self.client_address[0])
        now = time.time()
        with RATE_LIMIT_LOCK:
            window = RATE_LIMIT.get(ip)
            if window is None:
                window = []
                RATE_LIMIT[ip] = window
            window[:] = [t for t in window if now - t < RATE_LIMIT_WINDOW]
            if len(window) >= RATE_LIMIT_MAX:
                # Do NOT append — keeps the ban permanent until the window
                # naturally drains, with no path that can wedge longer.
                if len(RATE_LIMIT) > RATE_LIMIT_MAX_ENTRIES:
                    self._gc_rate_limit_locked(now)
                self._err("rate_limited")
                return False
            window.append(now)
            if len(RATE_LIMIT) > RATE_LIMIT_MAX_ENTRIES:
                self._gc_rate_limit_locked(now)
        return True

    def _gc_rate_limit_locked(self, now):
        # Caller must hold RATE_LIMIT_LOCK.
        for k in list(RATE_LIMIT.keys()):
            bucket = RATE_LIMIT[k]
            if not bucket or now - bucket[-1] > RATE_LIMIT_WINDOW:
                RATE_LIMIT.pop(k, None)
        if len(RATE_LIMIT) > RATE_LIMIT_MAX_ENTRIES:
            # Hard reset — bound the worst case.
            RATE_LIMIT.clear()

    def _err(self, code, **extra):
        spec = ERROR_CODES.get(code) or ERROR_CODES["internal_error"]
        body = {"error": spec["message"], "code": code}
        body.update(extra)
        self._json(body, spec["status"])

    def do_OPTIONS(self):
        self.send_response(204)
        origin = self._get_allowed_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def end_headers(self):
        # H-18: split query string off so file-extension matching and cache
        # headers apply to the underlying path, not the query-tainted form.
        path_only = urlsplit(self.path).path
        if not self.path.startswith("/api/"):
            csp = "default-src 'self' 'unsafe-inline' 'unsafe-eval' https://webapi.amap.com https://*.amap.com https://*.autonavi.com; img-src 'self' data: blob: https://*.amap.com https://*.autonavi.com; connect-src 'self' blob: https://*.amap.com https://*.autonavi.com; worker-src 'self' blob: https://*.amap.com https://*.autonavi.com; child-src 'self' blob: https://*.amap.com https://*.autonavi.com"
            self.send_header("Content-Security-Policy", csp)
        if path_only.endswith('.html') or path_only == '/':
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Content-Type', 'text/html; charset=utf-8')
        if path_only.endswith('.js'):
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
        if path_only.endswith('.css'):
            self.send_header('Content-Type', 'text/css; charset=utf-8')
        super().end_headers()

    def _json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        accept = self.headers.get("Accept-Encoding", "")
        if "gzip" in accept and len(raw) > 1024:
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
                gz.write(raw)
            compressed = buf.getvalue()
            self.send_response(status)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Content-Encoding","gzip")
            # H-18: send Content-Length alongside gzip so HTTP/1.1 keep-alive
            # proxies (e.g. nginx without chunked encoding) don't mis-frame.
            self.send_header("Content-Length", str(len(compressed)))
            origin = self._get_allowed_origin()
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.end_headers()
            self.wfile.write(compressed)
        else:
            self.send_response(status)
            self.send_header("Content-Type","application/json; charset=utf-8")
            origin = self._get_allowed_origin()
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.end_headers()
            self.wfile.write(raw)

if __name__ == "__main__":
    print("China Travel Map Server starting...")
    print(f"  Frontend: http://localhost:{PORT}/")
    print(f"  API: http://localhost:{PORT}/api/health")
    init_db()
    from http.server import ThreadingHTTPServer
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()