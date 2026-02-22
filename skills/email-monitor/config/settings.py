"""Загрузка конфигурации и env-переменных."""

import json
import os
import sys
from pathlib import Path


_config_cache = None


def get_skill_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def load_config(path: str | None = None) -> dict:
    global _config_cache
    if _config_cache and not path:
        return _config_cache
    if not path:
        path = get_skill_dir() / "config.json"
    with open(path, "r", encoding="utf-8") as f:
        _config_cache = json.load(f)
    return _config_cache


def get_gmail_credentials() -> tuple[str, str]:
    email = os.environ.get("GMAIL_EMAIL", "")
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not email or not app_password:
        cfg = load_config()
        email = email or cfg.get("gmail", {}).get("email", "")
    if not app_password:
        output_error("GMAIL_APP_PASSWORD не задан в переменных окружения")
    return email, app_password


def get_baserow_token() -> str:
    token = os.environ.get("BASEROW_TOKEN") or os.environ.get("BASEROW_API_TOKEN", "")
    if not token:
        output_error("BASEROW_TOKEN не задан")
    return token


def get_baserow_url() -> str:
    return os.environ.get("BASEROW_URL", "https://api.baserow.io")


def get_work_dir() -> Path:
    cfg = load_config()
    work_dir = Path(cfg.get("work_dir", "/dev/shm/email-monitor"))
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def output_json(data: dict | list) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def output_error(msg: str) -> None:
    print(json.dumps({"error": msg}, ensure_ascii=False), file=sys.stderr)
    sys.exit(1)
