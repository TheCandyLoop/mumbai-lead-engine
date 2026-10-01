"""Exercises the real Fetcher against a local HTTP server (no internet needed)."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from leadgen.enrichment import Fetcher, enrich_lead
from leadgen.models import Lead

PAGE = b"<html><body>Email info@local.test. Call +91 98200 11223. Hot desk and meeting room.</body></html>"
ROBOTS = b"User-agent: *\nDisallow: /private\n"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == "/robots.txt":
            self._send(200, ROBOTS, "text/plain")
        elif self.path in ("/", "/ok"):
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/private":
            self._send(200, PAGE, "text/html")
        elif self.path == "/file.pdf":
            self._send(200, b"%PDF", "application/pdf")
        else:
            self._send(404, b"nope", "text/plain")
    def _send(self, code, body, ctype):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


@pytest.fixture(scope="module")
def base():
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_fetcher_respects_robots_and_content_type(base):
    f = Fetcher(delay=0)
    assert "info@local.test" in f.get(base + "/ok")
    assert f.get(base + "/private") is None      # disallowed by robots.txt
    assert f.get(base + "/file.pdf") is None     # non-HTML
    assert f.get(base + "/missing") is None      # 404


def test_enrich_lead_end_to_end(base):
    l = Lead(company_name="Local", website=base + "/ok")
    # reserved-TLD skipping doesn't apply to 127.0.0.1, so this performs a real fetch
    from leadgen.enrichment import _skippable
    assert not _skippable(l.website)
    enrich_lead(l, Fetcher(delay=0))
    assert l.email == "info@local.test" and l.phone == "+919820011223"
    assert "hot desk" in l.services and l.is_complete
