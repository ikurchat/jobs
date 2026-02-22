"""Configuration and environment management for weekly-ops skill."""

import json
import os
import sys
import uuid
import shutil
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = SKILL_DIR / "config.json"


def load_config(config_path: Path | None = None) -> dict:
    """Load config.json and return parsed dict."""
    path = config_path or DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_baserow_url() -> str:
    """Get Baserow URL from environment. Raises RuntimeError if not set."""
    url = os.environ.get("BASEROW_URL")
    if not url:
        raise RuntimeError("BASEROW_URL environment variable is not set")
    if url.startswith("http://"):
        url = url.replace("http://", "https://", 1)
    return url.rstrip("/")


def get_baserow_token() -> str:
    """Get Baserow API token from environment. Raises RuntimeError if not set."""
    token = os.environ.get("BASEROW_TOKEN") or os.environ.get("BASEROW_API_TOKEN")
    if not token:
        raise RuntimeError(
            "BASEROW_TOKEN (or BASEROW_API_TOKEN) environment variable is not set"
        )
    return token


def get_table_id(config: dict, table_name: str) -> int:
    """Get Baserow table ID from config. Raises ValueError if not configured."""
    table_id = config.get("baserow", {}).get("tables", {}).get(table_name)
    if table_id is None:
        raise ValueError(
            f"Table '{table_name}' is not configured in config.json. "
            f"Create the table in Baserow and set the ID."
        )
    return int(table_id)


# ---------------------------------------------------------------------------
# Working directory management (/dev/shm)
# ---------------------------------------------------------------------------

def create_work_dir(config: dict) -> Path:
    """Create a unique working directory in /dev/shm."""
    base = Path(config.get("work_dir", "/dev/shm/weekly-ops"))
    session_id = uuid.uuid4().hex[:12]
    work_dir = base / session_id
    work_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    return work_dir


def cleanup_work_dir(work_dir: Path) -> None:
    """Remove working directory and all its contents."""
    if work_dir and work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Safe JSON output (for CLI scripts)
# ---------------------------------------------------------------------------

def output_json(data: dict | list) -> None:
    """Print JSON to stdout for consumption by SKILL.md."""
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def output_error(message: str, code: int = 1) -> None:
    """Print error JSON to stderr and exit."""
    print(
        json.dumps({"error": message}, ensure_ascii=False),
        file=sys.stderr,
    )
    sys.exit(code)
