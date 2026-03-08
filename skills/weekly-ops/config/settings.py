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


def get_db_path(config: dict | None = None) -> str:
    """Get SQLite database path from config."""
    if config is None:
        config = load_config()
    return config.get("db_path", "/data/weekly_ops.db")


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
