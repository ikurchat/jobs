"""Configuration for sed-monitor skill."""

import json
import os
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = SKILL_DIR / "config.json"


def load_config(config_path: Path | None = None) -> dict:
    path = config_path or DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_auth() -> dict:
    """Load SED credentials from secured file.

    Returns: {"login": ..., "user_id": ..., "group_id": ..., "password": ...}
    """
    config = load_config()
    auth_file = Path(config.get("auth_file", "/data/sed_auth.json"))
    if not auth_file.exists():
        raise FileNotFoundError(
            f"SED auth file not found: {auth_file}. "
            "Create it: owner says 'обнови пароль СЭД'"
        )
    with open(auth_file, "r", encoding="utf-8") as f:
        return json.load(f)


def save_auth(login: str, user_id: str, group_id: str, password: str) -> None:
    """Save SED credentials to secured file."""
    config = load_config()
    auth_file = Path(config.get("auth_file", "/data/sed_auth.json"))
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "login": login,
        "user_id": user_id,
        "group_id": group_id,
        "password": password,
    }
    with open(auth_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.chmod(auth_file, 0o600)


def get_proxy_url() -> str:
    config = load_config()
    return config.get("proxy_url", "http://sed-proxy:8443")


def get_db_path() -> str:
    config = load_config()
    return config.get("db_path", "/data/sed_monitor.db")
