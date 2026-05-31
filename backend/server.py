"""China Travel Map - HTTP API Server"""
import http.server, json, os, sys, gzip, io, time, hashlib
from urllib.parse import urlparse, parse_qs
from functools import wraps
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

HOST, PORT = "127.0.0.1", 8765
FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend")

# Security config
MAX_BODY_SIZE = 1024 * 1024  # 1MB max POST body
SEED_TOKEN = os.environ.get("SEED_TOKEN", "")  # Set this for /api/seed access
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "").split(",") or ["http://localhost:8765"]
RATE_LIMIT = {}  # Simple in-memory rate limiting: {ip: [(time, count), ...]}
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 60  # max requests per window

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=FRONTEND, **kw)

    def do_GET(self):
        if not self._check_rate_limit():
            return
        if self.path == "/api/init":
            init_db(); self._json({"ok":True})
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
                page=_si(g("page"), 1), page_size=min(_si(g("page_size"), 2000), 10000)
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
        else:
            super().do_GET()

    def do_POST(self):
        if not self._check_rate_limit():
            return
        if self.path == "/api/seed":
            # Check auth token
            token = self.headers.get("Authorization", "").replace("Bearer ", "")
            if not SEED_TOKEN or token != SEED_TOKEN:
                self._json({"error": "unauthorized"}, 401)
                return
            # Check body size
            cl = int(self.headers.get("Content-Length", 0))
            if cl > MAX_BODY_SIZE:
                self._json({"error": "request too large"}, 413)
                return
            body = json.loads(self.rfile.read(cl))
            insert_attractions(body.get("attractions",[]))
            insert_foods(body.get("foods",[]))
            self._json({"ok":True, "imported": len(body.get("attractions",[])) + len(body.get("foods",[]))})
        else:
            self._json({"error":"not found"}, 404)

    def _get_allowed_origin(self):
        origin = self.headers.get("Origin", "")
        if not origin:
            return "*"
        for allowed in ALLOWED_ORIGINS:
            if allowed and allowed.strip() and origin == allowed.strip():
                return origin
        return ""

    def _check_rate_limit(self):
        ip = self.headers.get("X-Real-IP", self.client_address[0])
        now = time.time()
        if ip not in RATE_LIMIT:
            RATE_LIMIT[ip] = []
        # Clean old entries
        RATE_LIMIT[ip] = [(t, n) for t, n in RATE_LIMIT[ip] if now - t < RATE_LIMIT_WINDOW]
        total = sum(n for _, n in RATE_LIMIT[ip]) + 1
        RATE_LIMIT[ip].append((now, 1))
        if total > RATE_LIMIT_MAX:
            self._json({"error": "rate limit exceeded, try again later"}, 429)
            return False
        return True

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
        if not self.path.startswith("/api/"):
            csp = "default-src 'self' 'unsafe-inline' 'unsafe-eval' https://webapi.amap.com https://*.amap.com https://*.autonavi.com; img-src 'self' data: https://*.amap.com https://*.autonavi.com; connect-src 'self' https://*.amap.com https://*.autonavi.com"
            self.send_header("Content-Security-Policy", csp)
        if self.path.endswith('.html') or self.path == '/':
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Content-Type', 'text/html; charset=utf-8')
        if self.path.endswith('.js'):
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
        if self.path.endswith('.css'):
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