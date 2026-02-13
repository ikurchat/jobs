"""
Common utilities for the OSINT skill.

CLI:
  python3 osint_utils.py cache_check <query_type> <query_value>
    → JSON {"cached": bool, "path": str|null, "age_hours": float|null}

  python3 osint_utils.py detect <text>
    → JSON {"query_type": str, "query_value": str}

  python3 osint_utils.py spend
    → JSON {"date": str, "total_credits": int, "query_count": int}
"""

import asyncio
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

# Lazy import — telethon available only inside Docker container
TelegramClient = None
StringSession = None


def _ensure_telethon():
    global TelegramClient, StringSession
    if TelegramClient is None:
        from telethon import TelegramClient as _TC
        from telethon.sessions import StringSession as _SS
        TelegramClient = _TC
        StringSession = _SS


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

OSINT_DIR = Path("/workspace/osint")
SESSION_PATH = Path("/data/telethon.session")
SPEND_LOG_PATH = OSINT_DIR / ".spend_log.json"

# ---------------------------------------------------------------------------
# Telethon client
# ---------------------------------------------------------------------------


def get_telethon_client():
    """Create a Telethon client from the stored StringSession."""
    _ensure_telethon()
    if not SESSION_PATH.exists():
        raise FileNotFoundError(
            f"Telethon session file not found: {SESSION_PATH}. "
            "Set up authorization first."
        )
    session_str = SESSION_PATH.read_text().strip()
    if not session_str:
        raise ValueError(f"Telethon session file is empty: {SESSION_PATH}")
    api_id = os.environ.get("TG_API_ID")
    api_hash = os.environ.get("TG_API_HASH")
    if not api_id or not api_hash:
        raise EnvironmentError(
            "TG_API_ID and TG_API_HASH environment variables must be set"
        )
    client = TelegramClient(
        StringSession(session_str),
        int(api_id),
        api_hash,
        device_model="arm64",
        system_version="23.5.0",
        app_version="1.36.0",
    )
    return client


# ---------------------------------------------------------------------------
# Polling helpers
# ---------------------------------------------------------------------------


async def wait_for_response(
    client,
    entity,
    after_id: int,
    timeout: int = 30,
    poll_interval: int = 2,
):
    """Wait for a single NEW message from *entity* with id > after_id."""
    deadline = time.time() + timeout
    bot_id = getattr(entity, "id", None)

    while time.time() < deadline:
        messages = await client.get_messages(entity, limit=5)
        for msg in messages:
            if msg.id > after_id and not getattr(msg, "out", False):
                sender_id = getattr(msg, "sender_id", None)
                if sender_id == bot_id:
                    return msg
        await asyncio.sleep(poll_interval)
    return None


async def wait_for_all_responses(
    client,
    entity,
    after_id: int,
    timeout: int = 60,
    silence_timeout: int = 5,
    poll_interval: int = 2,
):
    """Collect ALL messages from *entity* until it stays silent for *silence_timeout* seconds.

    Critical for Sherlock Report which may reply with multiple messages.
    """
    collected: list = []
    seen_ids: set[int] = set()
    deadline = time.time() + timeout
    last_message_time = time.time()
    bot_id = getattr(entity, "id", None)

    while time.time() < deadline:
        messages = await client.get_messages(entity, limit=10)
        for msg in messages:
            if msg.id > after_id and msg.id not in seen_ids:
                if getattr(msg, "out", False):
                    continue
                sender_id = getattr(msg, "sender_id", None)
                if sender_id == bot_id:
                    collected.append(msg)
                    seen_ids.add(msg.id)
                    last_message_time = time.time()
                    after_id = max(after_id, msg.id)

        if collected and (time.time() - last_message_time) >= silence_timeout:
            break

        await asyncio.sleep(poll_interval)

    collected.sort(key=lambda m: m.id)
    return collected


async def wait_for_message_edit(
    client,
    entity,
    message_id: int,
    timeout: int = 15,
    poll_interval: int = 2,
    original_text: str | None = None,
    original_edit_date=None,
):
    """Wait for a specific message to be edited (inline-button response pattern).

    If original_text/original_edit_date are provided, use them as baseline
    (avoids race condition when edit happens between click and this call).
    """
    if original_text is None or original_edit_date is ...:
        original = await client.get_messages(entity, ids=message_id)
        if not original:
            return None
        original_text = original.text or ""
        original_edit_date = original.edit_date

    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = await client.get_messages(entity, ids=message_id)
        if msg:
            if msg.edit_date != original_edit_date or (msg.text or "") != original_text:
                return msg
        await asyncio.sleep(poll_interval)
    return None


# ---------------------------------------------------------------------------
# Inline-button helper
# ---------------------------------------------------------------------------


async def click_inline_button(message, target_text: str) -> bool:
    """Find an inline button by partial text match (case-insensitive) and click it.

    Only works with inline keyboards (ReplyInlineMarkup) and callback buttons.
    Returns False for URL buttons, switch-inline buttons, or regular keyboards.
    """
    if not message or not message.reply_markup:
        return False
    if not hasattr(message.reply_markup, "rows"):
        return False
    target = target_text.lower()
    for i, row in enumerate(message.reply_markup.rows):
        for j, button in enumerate(row.buttons):
            if target in button.text.lower():
                # Only click callback buttons that have .data
                if getattr(button, "data", None) is not None:
                    await message.click(i, j)
                    return True
                # Non-callback button (URL, switch-inline) — cannot be clicked
                return False
    return False


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _sanitize_value(query_value: str) -> str:
    """Sanitize query value for use in filesystem paths. ASCII-only."""
    return re.sub(r"[^a-zA-Z0-9_@.+\-]", "_", query_value)


def _cache_dir(query_type: str, query_value: str) -> Path | None:
    """Return the newest cache directory matching the query, or None."""
    if not OSINT_DIR.exists():
        return None
    safe_value = _sanitize_value(query_value)
    pattern = f"*_{query_type}_{safe_value}"
    matches = sorted(OSINT_DIR.glob(pattern), reverse=True)
    return matches[0] if matches else None


def check_cache(query_type: str, query_value: str, max_age_hours: float = 24) -> dict:
    """Check if we have fresh cached results for a query."""
    cache = _cache_dir(query_type, query_value)
    if cache is None:
        return {"cached": False, "path": None, "age_hours": None}

    files = [f for f in cache.iterdir() if f.is_file()]
    if not files:
        return {"cached": False, "path": None, "age_hours": None}

    newest_mtime = max(f.stat().st_mtime for f in files)
    age_hours = (time.time() - newest_mtime) / 3600
    if age_hours < max_age_hours:
        return {"cached": True, "path": str(cache), "age_hours": round(age_hours, 2)}
    return {"cached": False, "path": str(cache), "age_hours": round(age_hours, 2)}


def save_result(
    query_type: str,
    query_value: str,
    source: str,
    suffix: str,
    text: str,
) -> str:
    """Save a result file and return the path."""
    safe_value = _sanitize_value(query_value)
    today = date.today().isoformat()
    dir_name = f"{today}_{query_type}_{safe_value}"
    directory = OSINT_DIR / dir_name

    # Path traversal guard
    resolved = directory.resolve()
    osint_resolved = OSINT_DIR.resolve()
    if not str(resolved).startswith(str(osint_resolved)):
        raise ValueError(f"Path traversal detected: {directory}")

    directory.mkdir(parents=True, exist_ok=True)

    filename = f"{source}_{suffix}.txt"
    path = directory / filename
    path.write_text(text, encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Balance helpers (shared by both bots)
# ---------------------------------------------------------------------------

INSUFFICIENT_BALANCE_PHRASES = [
    "недостаточно",
    "not enough",
    "баланс исчерпан",
    "пополните",
    "лимит превышен",
    "нет средств",
    "top up",
    "no credits",
    "no balance",
    "оплат",
    "balance is 0",
    "баланс: 0",
    "закончились",
    "исчерпан",
]

BALANCE_PATTERNS = [
    r"(?:осталось|запросов|balance|remaining|доступно|баланс)[:\s]*(\d+)",
    r"(\d+)\s*(?:запрос|request|поиск|search|кредит|credit)",
    r"(?:лимит|limit)[:\s]*\d+\s*/\s*(\d+)",
]


def is_insufficient_balance(text: str) -> bool:
    """Check if a bot response indicates insufficient balance."""
    if not text:
        return False
    lower = text.lower()
    return any(phrase in lower for phrase in INSUFFICIENT_BALANCE_PHRASES)


def parse_balance(text: str) -> int | None:
    """Extract a numeric balance from bot response text."""
    if not text:
        return None
    for pattern in BALANCE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


# ---------------------------------------------------------------------------
# Spend tracking
# ---------------------------------------------------------------------------


def log_spend(bot_name: str, query_type: str, query_value: str, cost: int = 1) -> dict:
    """Log a query spend event. Returns updated daily stats."""
    today = date.today().isoformat()
    log = _load_spend_log()

    if today not in log:
        log[today] = {"total": 0, "queries": []}

    log[today]["total"] += cost
    log[today]["queries"].append({
        "bot": bot_name,
        "type": query_type,
        "value": query_value[:20],  # truncate for privacy
        "cost": cost,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    _save_spend_log(log)
    return {"today_total": log[today]["total"], "today_queries": len(log[today]["queries"])}


def get_daily_spend() -> dict:
    """Get today's spend summary."""
    today = date.today().isoformat()
    log = _load_spend_log()
    day_data = log.get(today, {"total": 0, "queries": []})
    return {
        "date": today,
        "total_credits": day_data["total"],
        "query_count": len(day_data["queries"]),
    }


def _load_spend_log() -> dict:
    if SPEND_LOG_PATH.exists():
        try:
            return json.loads(SPEND_LOG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_spend_log(data: dict) -> None:
    OSINT_DIR.mkdir(parents=True, exist_ok=True)
    SPEND_LOG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize_phone(raw: str) -> str:
    """Normalize phone to 7XXXXXXXXXX."""
    digits = re.sub(r"[^\d]", "", raw)
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    if not digits.startswith("7"):
        digits = "7" + digits
    return digits[:11]


def normalize_username(raw: str) -> str:
    """Strip @ prefix."""
    return raw.lstrip("@").strip()


# ---------------------------------------------------------------------------
# Input type detection
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, re.Pattern, str | None]] = [
    # Order matters — more specific first
    ("email", re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$"), None),
    ("auto_vin", re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.IGNORECASE), None),
    ("auto_plate", re.compile(r"^[АВЕКМНОРСТУХABEKMHOPCTYX]\d{3}[АВЕКМНОРСТУХABEKMHOPCTYX]{2}\d{2,3}$", re.IGNORECASE), None),
    ("cadastre", re.compile(r"^\d{2}:\d{2}:\d{6,7}:\d+$"), None),
    ("ogrn", re.compile(r"^\d{13}$"), None),
    ("phone", re.compile(r"^[+]?[78]\d{10}$"), None),
    ("phone", re.compile(r"^\d{10}$"), None),
    ("social", re.compile(r"(vk\.com|ok\.ru|instagram\.com|tiktok\.com|facebook\.com|twitter\.com)/\S+", re.IGNORECASE), None),
    ("domain_ip", re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"), None),
    ("domain_ip", re.compile(r"^[a-zA-Z0-9-]+\.[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"), None),
    ("domain_ip", re.compile(r"^[a-zA-Z0-9-]+\.[a-zA-Z]{2,6}$"), None),
    ("username", re.compile(r"^@?[a-zA-Z][\w]{3,31}$"), None),
]

_DOC_COMMANDS = {
    "/passport": "document",
    "/vu": "document",
    "/snils": "document",
    "/inn": "document",
    "/adr": "address",
}

_FIO_RE = re.compile(
    r"^[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?(?:\s+\d{2}\.\d{2}\.\d{4})?$"
)


def detect_query_type(text: str) -> tuple[str, str]:
    """Detect (query_type, normalized_value) from free-form text."""
    text = text.strip()

    for cmd, qtype in _DOC_COMMANDS.items():
        if text.lower().startswith(cmd):
            return qtype, text

    if _FIO_RE.match(text):
        return "fio", text

    cleaned = text.lstrip("@+")

    for qtype, pattern, _ in _PATTERNS:
        if pattern.search(cleaned):
            if qtype == "phone":
                return "phone", normalize_phone(text)
            if qtype == "username":
                return "username", normalize_username(text)
            return qtype, text

    if re.search(r"[А-ЯЁа-яё]", text) and " " in text:
        return "fio", text

    return "unknown", text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: osint_utils.py <command> [args]"}))
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "cache_check":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: cache_check <query_type> <query_value>"}))
            sys.exit(1)
        result = check_cache(sys.argv[2], sys.argv[3])
        print(json.dumps(result))

    elif cmd == "detect":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: detect <text>"}))
            sys.exit(1)
        text = " ".join(sys.argv[2:])
        qtype, qvalue = detect_query_type(text)
        print(json.dumps({"query_type": qtype, "query_value": qvalue}))

    elif cmd == "spend":
        result = get_daily_spend()
        print(json.dumps(result))

    else:
        print(json.dumps({"error": f"Unknown command: {cmd}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
