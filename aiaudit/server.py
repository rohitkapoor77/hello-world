"""A dependency-free web UI + JSON API for the auditor, built on
``http.server``. Run via ``python run.py`` (see project root).

Endpoints
---------
GET  /                     -> the single-page UI
GET  /<asset>              -> static files from the web/ directory
POST /api/audit            -> {"urls": [...]} => {"results": [...], "summary": {...}}
POST /api/export?format=.. -> {"results": [...]} => CSV or XLSX download
"""
from __future__ import annotations

import json
import os
import posixpath
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import APP_NAME, VERSION, MAX_URLS
from .engine import audit_batch, batch_summary
from . import exporter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    server_version = f"AIShoppingReadinessAuditor/{VERSION}"

    # ------------------------------------------------------------------ utils
    def _send(self, status, body, content_type="application/json; charset=utf-8",
              extra_headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj), "application/json; charset=utf-8")

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    # -------------------------------------------------------------------- GET
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/" or path == "":
            return self._serve_file("index.html")
        if path == "/api/health":
            return self._json(200, {"ok": True, "app": APP_NAME, "version": VERSION,
                                    "max_urls": MAX_URLS})
        # static asset
        safe = posixpath.normpath(path).lstrip("/")
        if safe in ("", ".") or safe.startswith(".."):
            return self._send(404, "Not found", "text/plain; charset=utf-8")
        return self._serve_file(safe)

    def do_HEAD(self):
        self.do_GET()

    def _serve_file(self, rel):
        full = os.path.join(WEB_DIR, rel)
        if not os.path.isfile(full):
            return self._send(404, "Not found", "text/plain; charset=utf-8")
        ext = os.path.splitext(full)[1].lower()
        ctype = _CONTENT_TYPES.get(ext, "application/octet-stream")
        with open(full, "rb") as fh:
            data = fh.read()
        return self._send(200, data, ctype)

    # ------------------------------------------------------------------- POST
    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/audit":
            return self._handle_audit()
        if parsed.path == "/api/export":
            return self._handle_export(parse_qs(parsed.query))
        return self._json(404, {"error": "Unknown endpoint."})

    def _handle_audit(self):
        body = self._read_json()
        if body is None:
            return self._json(400, {"error": "Invalid JSON body."})
        urls = body.get("urls") or []
        if isinstance(urls, str):
            urls = [urls]
        urls = [u for u in (s.strip() for s in urls) if u]
        if not urls:
            return self._json(400, {"error": "Provide at least one URL."})
        truncated = len(urls) > MAX_URLS
        try:
            results = audit_batch(urls)
        except Exception as exc:  # pragma: no cover
            return self._json(500, {"error": f"Audit failed: {exc}"})
        return self._json(200, {
            "results": results,
            "summary": batch_summary(results),
            "truncated": truncated,
            "max_urls": MAX_URLS,
        })

    def _handle_export(self, query):
        body = self._read_json()
        if body is None:
            return self._json(400, {"error": "Invalid JSON body."})
        results = body.get("results") or []
        if not results:
            return self._json(400, {"error": "No results to export."})
        fmt = (query.get("format", ["csv"])[0] or "csv").lower()
        kind = (query.get("kind", ["summary"])[0] or "summary").lower()
        if fmt == "xlsx":
            data = exporter.to_xlsx(results)
            return self._send(
                200, data,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                {"Content-Disposition": 'attachment; filename="ai-readiness-audit.xlsx"'},
            )
        # CSV
        text = exporter.to_checks_csv(results) if kind == "checks" else exporter.to_csv(results)
        fname = "ai-readiness-checks.csv" if kind == "checks" else "ai-readiness-summary.csv"
        return self._send(
            200, text, "text/csv; charset=utf-8",
            {"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    def log_message(self, fmt, *args):  # quieter logging
        return


def serve(host="127.0.0.1", port=8000):
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"\n  {APP_NAME} v{VERSION}")
    print(f"  Serving on {url}")
    print(f"  Audit up to {MAX_URLS} product URLs at once. Press Ctrl+C to stop.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Shutting down.")
    finally:
        httpd.server_close()
    return httpd
