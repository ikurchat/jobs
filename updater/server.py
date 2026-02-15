"""
Updater HTTP server — проверка и применение обновлений из git.

Работает напрямую с хостовым git-репозиторием (COMPOSE_DIR),
без отдельного клона. docker compose build/up из той же директории.

Dual-remote strategy:
  upstream = qanelph/jobs  (основной репо, источник обновлений)
  origin   = ikurchat/jobs (форк, кастомные изменения)

/check   — fetch upstream + сравнение HEAD vs upstream/main
/update  — fetch upstream + merge + build + restart
"""

import json
import os
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler

COMPOSE_DIR = os.environ.get("COMPOSE_DIR", "")
BRANCH = "main"

# Upstream = основной репо (источник обновлений)
UPSTREAM_REMOTE = "upstream"
# Origin = форк (кастомные изменения, для /check показываем оба)
ORIGIN_REMOTE = "origin"


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


def _try_run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str] | None:
    """Run command, return None on failure instead of raising."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=600)
    return result if result.returncode == 0 else None


def _get_new_commits(base: str, target: str) -> list[dict[str, str]]:
    """Get list of commits between base..target."""
    commits: list[dict[str, str]] = []
    if base == target:
        return commits
    result = _try_run(
        ["git", "log", "--oneline", f"{base}..{target}"],
        cwd=COMPOSE_DIR,
    )
    if result and result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            if line:
                hash_, _, message = line.partition(" ")
                commits.append({"hash": hash_, "message": message})
    return commits


def check_updates() -> dict:
    """Fetch upstream and origin, report new commits from both."""
    current = run(["git", "rev-parse", "HEAD"], cwd=COMPOSE_DIR).stdout.strip()

    # Fetch upstream (qanelph/jobs)
    upstream_commits: list[dict[str, str]] = []
    upstream_latest = current
    try:
        run(["git", "fetch", UPSTREAM_REMOTE, BRANCH], cwd=COMPOSE_DIR)
        upstream_latest = run(
            ["git", "rev-parse", f"{UPSTREAM_REMOTE}/{BRANCH}"],
            cwd=COMPOSE_DIR,
        ).stdout.strip()
        upstream_commits = _get_new_commits(current, upstream_latest)
    except RuntimeError:
        pass  # upstream may not be configured

    # Fetch origin (ikurchat/jobs)
    origin_commits: list[dict[str, str]] = []
    origin_latest = current
    try:
        run(["git", "fetch", ORIGIN_REMOTE, BRANCH], cwd=COMPOSE_DIR)
        origin_latest = run(
            ["git", "rev-parse", f"{ORIGIN_REMOTE}/{BRANCH}"],
            cwd=COMPOSE_DIR,
        ).stdout.strip()
        origin_commits = _get_new_commits(current, origin_latest)
    except RuntimeError:
        pass  # origin may not be configured

    # Combined: any new commits from either source
    all_commits = upstream_commits + [
        c for c in origin_commits
        if c["hash"] not in {uc["hash"] for uc in upstream_commits}
    ]

    return {
        "current": current,
        "upstream_latest": upstream_latest,
        "origin_latest": origin_latest,
        "commits": all_commits,
        "upstream_commits": len(upstream_commits),
        "origin_commits": len(origin_commits),
    }


def apply_update() -> dict:
    """Merge upstream/main into local, then build + restart."""
    # Запоминаем tree-hash browser/ до merge
    old_browser = run(
        ["git", "rev-parse", "HEAD:browser"],
        cwd=COMPOSE_DIR,
    ).stdout.strip()

    merged_from: list[str] = []

    # 1. Merge upstream (qanelph/jobs) — основные обновления
    try:
        run(["git", "fetch", UPSTREAM_REMOTE, BRANCH], cwd=COMPOSE_DIR)
        current = run(["git", "rev-parse", "HEAD"], cwd=COMPOSE_DIR).stdout.strip()
        upstream_head = run(
            ["git", "rev-parse", f"{UPSTREAM_REMOTE}/{BRANCH}"],
            cwd=COMPOSE_DIR,
        ).stdout.strip()

        if current != upstream_head:
            run(
                ["git", "merge", f"{UPSTREAM_REMOTE}/{BRANCH}", "--no-edit"],
                cwd=COMPOSE_DIR,
            )
            merged_from.append("upstream")
    except RuntimeError as e:
        # If merge conflict — abort and report
        _try_run(["git", "merge", "--abort"], cwd=COMPOSE_DIR)
        raise RuntimeError(f"upstream merge failed: {e}")

    # 2. Merge origin (ikurchat/jobs) — форковые обновления
    try:
        run(["git", "fetch", ORIGIN_REMOTE, BRANCH], cwd=COMPOSE_DIR)
        current = run(["git", "rev-parse", "HEAD"], cwd=COMPOSE_DIR).stdout.strip()
        origin_head = run(
            ["git", "rev-parse", f"{ORIGIN_REMOTE}/{BRANCH}"],
            cwd=COMPOSE_DIR,
        ).stdout.strip()

        if current != origin_head:
            run(
                ["git", "merge", f"{ORIGIN_REMOTE}/{BRANCH}", "--no-edit"],
                cwd=COMPOSE_DIR,
            )
            merged_from.append("origin")
    except RuntimeError as e:
        _try_run(["git", "merge", "--abort"], cwd=COMPOSE_DIR)
        raise RuntimeError(f"origin merge failed: {e}")

    if not merged_from:
        return {"ok": True, "message": "already up to date"}

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

    return {"ok": True, "merged_from": merged_from}


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
