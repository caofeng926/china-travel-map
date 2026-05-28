"""China Travel Map - HTTP API Server"""
import http.server, json, os, sys, gzip, io
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(__file__))
from database import init_db, search_pois, get_stats, insert_attractions, insert_foods
from trip_planner import plan_trip

HOST, PORT = "0.0.0.0", 8765
FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend")

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=FRONTEND, **kw)

    def do_GET(self):
        if self.path == "/api/init":
            init_db(); self._json({"ok":True})
        elif self.path == "/api/stats":
            self._json(get_stats())
        elif self.path.startswith("/api/pois"):
            p = parse_qs(urlparse(self.path).query)
            def g(k, d=None): return p.get(k, [d])[0]
            self._json(search_pois(
                compact=g("compact", "1") == "1",
                center_lat=float(g("lat", 0)) if g("lat") else None,
                center_lng=float(g("lng", 0)) if g("lng") else None,
                radius_km=float(g("radius", 500)),
                rating=g("rating"), type_filter=g("type"),
                keyword=g("keyword"), province=g("province"), city=g("city"),
                page=int(g("page", 1)), page_size=int(g("page_size", 500))
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
        if self.path == "/api/seed":
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length",0))))
            insert_attractions(body.get("attractions",[]))
            insert_foods(body.get("foods",[]))
            self._json({"ok":True})
        else:
            self._json({"error":"not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.end_headers()

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
            self.send_header("Access-Control-Allow-Origin","*")
            self.end_headers()
            self.wfile.write(compressed)
        else:
            self.send_response(status)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin","*")
            self.end_headers()
            self.wfile.write(raw)

if __name__ == "__main__":
    print("China Travel Map Server starting...")
if __name__ == "__main__":
    print("China Travel Map Server starting...")
    print(f"  Frontend: http://localhost:{PORT}/")
    print(f"  API: http://localhost:{PORT}/api/health")
    init_db()
    from http.server import ThreadingHTTPServer
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()