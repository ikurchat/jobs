"""
Updater HTTP server — проверка и применение обновлений из git.

Работает напрямую с хостовым git-репозиторием (COMPOSE_DIR),
без отдельного клона. docker compose build/up из той же директории.

Endpoints:
  GET  /check  — fetch + сравнение HEAD vs origin/main
  POST /update — pull + build + restart
"""

import json
import os
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler

COMPOSE_DIR = os.environ.get("COMPOSE_DIR", "")
BRANCH = "main"


def _configure_git() -> None:
    """Разрешает git работать с хостовым репо (другой owner)."""
    subprocess.run(
        ["git", "config", "--global", "--add", "safe.directory", COMPOSE_DIR],
        capture_output=True,
    )


def run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}: {result.stderr.strip()}")
    return result


def check_updates() -> dict:
    run(["git", "fetch", "origin", BRANCH], cwd=COMPOSE_DIR)

    current = run(["git", "rev-parse", "HEAD"], cwd=COMPOSE_DIR).stdout.strip()
    latest = run(["git", "rev-parse", f"origin/{BRANCH}"], cwd=COMPOSE_DIR).stdout.strip()

    commits: list[dict[str, str]] = []
    if current != latest:
        log = run(
            ["git", "log", "--oneline", f"{current}..{latest}"],
            cwd=COMPOSE_DIR,
        ).stdout.strip()
        for line in log.splitlines():
            if line:
                hash_, _, message = line.partition(" ")
                commits.append({"hash": hash_, "message": message})

    return {"current": current, "latest": latest, "commits": commits}


def apply_update() -> dict:
    # Запоминаем tree-hash browser/ до pull
    old_browser = run(
        ["git", "rev-parse", "HEAD:browser"],
        cwd=COMPOSE_DIR,
    ).stdout.strip()

    run(["git", "pull", "origin", BRANCH], cwd=COMPOSE_DIR)

    new_browser = run(
        ["git", "rev-parse", "HEAD:browser"],
        cwd=COMPOSE_DIR,
    ).stdout.strip()

    # Build + restart
    services = ["jobs"]
    if old_browser != new_browser:
        services.append("browser")

    run(["docker", "compose", "build"] + services, cwd=COMPOSE_DIR)
    run(["docker", "compose", "up", "-d"] + services, cwd=COMPOSE_DIR)

    return {"ok": True}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/check":
            self._handle(check_updates)
        else:
            self._json_response({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        if self.path == "/update":
            self._handle(apply_update)
        else:
            self._json_response({"error": "not found"}, status=404)

    def _handle(self, fn: callable) -> None:
        try:
            self._json_response(fn())
        except Exception as e:
            self._json_response({"error": str(e)}, status=500)

    def _json_response(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[updater] {args[0]}")


if __name__ == "__main__":
    _configure_git()
    server = HTTPServer(("0.0.0.0", 9100), Handler)
    print(f"[updater] listening on :9100, compose_dir={COMPOSE_DIR}")
    server.serve_forever()
