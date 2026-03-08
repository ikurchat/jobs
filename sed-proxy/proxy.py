"""GOST TLS reverse proxy for СЭД Практика.

Accepts plain HTTP from jobs container, forwards to doc.rscc.ru:444
with GOST TLS client certificate. Runs inside rnix/openssl-gost container.

Endpoints:
  POST /graphql          → POST https://doc.rscc.ru:444/mont/api
  GET  /alive            → GET  https://doc.rscc.ru:444/mont/alive
  POST /auth             → POST https://doc.rscc.ru:444/auth.php
  GET  /web              → GET  https://doc.rscc.ru:444/web/...
  GET  /file/<path>      → GET  https://doc.rscc.ru:444/<path>
  GET  /health           → 200 OK
"""

import json
import os
import subprocess
import sys
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs

SERVER = os.environ.get("SED_SERVER", "doc.rscc.ru")
CERT_PATH = "/certs/cert.pem"
KEY_PATH = "/certs/key.pem"
CIPHERS = "GOST2012-GOST8912-GOST8912"
PORT = int(os.environ.get("PROXY_PORT", "8443"))


def _curl(url, method="GET", headers=None, data=None, dump_headers=False,
          raw=False):
    """Execute curl with GOST TLS.

    If raw=True, returns bytes without decoding (for binary files).
    """
    cmd = [
        "curl", "-sk", "--connect-timeout", "15", "--max-time", "60",
        "--cert", CERT_PATH, "--key", KEY_PATH,
        "--ciphers", CIPHERS, "-X", method,
    ]
    if dump_headers:
        cmd.append("-D-")
    if headers:
        for k, v in headers.items():
            cmd += ["-H", f"{k}: {v}"]
    if data:
        cmd += ["-d", data]
    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=65)
        if raw:
            return result.stdout
        try:
            return result.stdout.decode("utf-8")
        except UnicodeDecodeError:
            return result.stdout.decode("windows-1251", errors="replace")
    except subprocess.TimeoutExpired:
        return b"" if raw else '{"error": "timeout"}'
    except Exception as e:
        return b"" if raw else json.dumps({"error": str(e)})


class ProxyHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler that proxies to SED server with GOST TLS."""

    def log_message(self, format, *args):
        """Suppress default logging to keep it quiet."""
        pass

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _get_cookies(self):
        return self.headers.get("X-SED-Cookies", "")

    def _send_response(self, body, content_type="application/json", status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_response('{"status": "ok"}')
            return

        if self.path == "/alive":
            raw = _curl(f"https://{SERVER}:444/mont/alive", dump_headers=True)
            self._send_response(raw or '{"error": "no response"}')
            return

        if self.path.startswith("/web"):
            cookies = self._get_cookies()
            headers = {}
            if cookies:
                headers["Cookie"] = cookies
            # Pass query string
            url = f"https://{SERVER}:444{self.path}"
            raw = _curl(url, headers=headers)
            self._send_response(raw or '{"error": "no response"}')
            return

        if self.path.startswith("/file/"):
            # Download file (document page image) — raw binary
            file_path = self.path[5:]  # remove /file prefix
            cookies = self._get_cookies()
            headers = {}
            if cookies:
                headers["Cookie"] = cookies
            data = _curl(f"https://{SERVER}:444{file_path}", headers=headers,
                         raw=True)
            self._send_response(data or b"", content_type="application/octet-stream")
            return

        self._send_response('{"error": "unknown endpoint"}', status=404)

    def do_POST(self):
        body = self._read_body()
        cookies = self._get_cookies()

        if self.path == "/graphql":
            headers = {"Content-Type": "application/json"}
            if cookies:
                headers["Cookie"] = cookies
            raw = _curl(
                f"https://{SERVER}:444/mont/api",
                method="POST", headers=headers,
                data=body.decode("utf-8") if body else None,
            )
            self._send_response(raw or '{"error": "no response"}')
            return

        if self.path == "/auth":
            # Forward auth request with dump_headers to capture Set-Cookie
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
            }
            referer = self.headers.get("X-SED-Referer", "")
            if referer:
                headers["Referer"] = referer
            raw = _curl(
                f"https://{SERVER}:444/auth.php{self._get_query_string()}",
                method="POST", headers=headers,
                data=body.decode("utf-8") if body else None,
                dump_headers=True,
            )
            self._send_response(raw or '{"error": "no response"}')
            return

        self._send_response('{"error": "unknown endpoint"}', status=404)

    def _get_query_string(self):
        """Extract query string from X-SED-Query header."""
        qs = self.headers.get("X-SED-Query", "")
        return f"?{qs}" if qs else ""


def main():
    # Verify certs exist
    for path in (CERT_PATH, KEY_PATH):
        if not os.path.exists(path):
            print(f"[!] Missing: {path}", file=sys.stderr)
            sys.exit(1)

    server = HTTPServer(("0.0.0.0", PORT), ProxyHandler)
    print(f"[sed-proxy] Listening on :{PORT}, target={SERVER}:444", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
