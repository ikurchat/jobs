"""Configuration for sed-monitor skill."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = SKILL_DIR / "config.json"

_TOKEN_PATH = Path("/data/sed_token.json")
_USER_ID = "81081"


def load_config(config_path: Path | None = None) -> dict:
    path = config_path or DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_token() -> dict | None:
    """Load saved SED token.

    Returns: {"dnsid": ..., "auth_token": ..., "created": ...} or None.
    """
    if not _TOKEN_PATH.exists():
        return None
    with open(_TOKEN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_token(dnsid: str, auth_token: str) -> None:
    """Save SED token (DNSID + auth_token). No password stored."""
    _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "dnsid": dnsid,
        "auth_token": auth_token,
        "user_id": _USER_ID,
        "created": datetime.now(timezone.utc).isoformat(),
    }
    with open(_TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.chmod(_TOKEN_PATH, 0o600)


def get_user_id() -> str:
    return _USER_ID


def get_proxy_url() -> str:
    config = load_config()
    return config.get("proxy_url", "http://sed-proxy:8443")


def get_db_path() -> str:
    config = load_config()
    return config.get("db_path", "/data/sed_monitor.db")
