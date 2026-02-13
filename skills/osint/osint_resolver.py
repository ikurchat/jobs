"""
Bot URL resolver for OSINT skill.

Both Cilordbot and Sherlock Report change their usernames when blocked.
This module resolves current bot usernames using multiple methods.

Storage: /workspace/osint/.bot_urls.json

CLI:
  python3 osint_resolver.py resolve sherlock
  python3 osint_resolver.py resolve cilord
  python3 osint_resolver.py status
  python3 osint_resolver.py save sherlock "@new_bot"
  python3 osint_resolver.py save cilord "@new_bot"
  python3 osint_resolver.py validate "@bot_username"
"""

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from osint_utils import get_telethon_client, wait_for_response

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

OSINT_DIR = Path("/workspace/osint")
BOT_URLS_PATH = OSINT_DIR / ".bot_urls.json"
CACHE_MAX_AGE_DAYS = 7

# ---------------------------------------------------------------------------
# Cache read/write
# ---------------------------------------------------------------------------


def _load_cache() -> dict:
    if BOT_URLS_PATH.exists():
        try:
            return json.loads(BOT_URLS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_cache(data: dict) -> None:
    OSINT_DIR.mkdir(parents=True, exist_ok=True)
    BOT_URLS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def save_bot(name: str, username: str) -> dict:
    """Save a resolved bot username to cache."""
    username = username.lstrip("@")
    cache = _load_cache()
    cache[name] = {
        "username": f"@{username}",
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_cache(cache)
    return cache[name]


def _get_cached(name: str) -> str | None:
    """Get cached bot username if fresh enough (< CACHE_MAX_AGE_DAYS)."""
    cache = _load_cache()
    entry = cache.get(name)
    if not entry:
        return None

    resolved_at = datetime.fromisoformat(entry["resolved_at"])
    age_days = (datetime.now(timezone.utc) - resolved_at).total_seconds() / 86400
    if age_days > CACHE_MAX_AGE_DAYS:
        return None
    return entry["username"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


async def validate_bot(client, username: str, timeout: int = 15) -> bool:
    """Validate that a bot responds to /start within timeout."""
    try:
        entity = await client.get_entity(username)
        last_msg = await client.get_messages(entity, limit=1)
        after_id = last_msg[0].id if last_msg else 0

        await client.send_message(entity, "/start")
        response = await wait_for_response(client, entity, after_id, timeout=timeout)
        return response is not None
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------


async def resolve_sherlock(client) -> dict:
    """Resolve current Sherlock Report bot username.

    Priority:
    1. Cache (< 7 days) + validate
    2. Telegram channel @report_sherlok — parse last posts for t.me/ links
    3. Fallback: agent should use browser (returned as instruction)
    """
    # 1. Cache
    cached = _get_cached("sherlock")
    if cached:
        if await validate_bot(client, cached):
            return {"username": cached, "method": "cache", "valid": True}

    # 2. Telegram channel
    try:
        channel = await client.get_entity("report_sherlok")
        messages = await client.get_messages(channel, limit=5)
        for msg in messages:
            if not msg.text:
                continue
            matches = re.findall(r"t\.me/(\w+)", msg.text)
            for match in matches:
                candidate = f"@{match}"
                if match.lower() in ("report_sherlok", "joinchat"):
                    continue
                if await validate_bot(client, candidate):
                    save_bot("sherlock", match)
                    return {"username": candidate, "method": "telegram", "valid": True}
    except Exception:
        pass

    # 3. Fallback — instruct agent to use browser
    return {
        "username": None,
        "method": "needs_browser",
        "valid": False,
        "instruction": (
            "Could not resolve Sherlock bot via Telegram. "
            "Use browser: browser_navigate('https://dc6.sherlock.report/start') "
            "→ browser_snapshot() → extract bot username from redirect/page. "
            "Then run: python3 osint_resolver.py save sherlock @new_bot_username"
        ),
    }


async def resolve_cilord(client) -> dict:
    """Resolve current Cilordbot (telelog) username.

    Priority:
    1. Cache (< 7 days) + validate
    2. Fallback: agent should use browser with bit.ly redirect
    """
    # 1. Cache
    cached = _get_cached("cilord")
    if cached:
        if await validate_bot(client, cached):
            return {"username": cached, "method": "cache", "valid": True}

    # 2. Fallback — instruct agent to use browser
    return {
        "username": None,
        "method": "needs_browser",
        "valid": False,
        "instruction": (
            "Could not resolve Cilord bot from cache. "
            "Use browser: browser_navigate('http://bit.ly/4kIt4t9') → follows redirect to telelog.org "
            "→ browser_snapshot() → extract t.me/... bot link. "
            "Then run: python3 osint_resolver.py save cilord @new_bot_username"
        ),
    }


async def get_status(client) -> dict:
    """Get status of both bots."""
    result = {}
    for name in ("cilord", "sherlock"):
        cached = _get_cached(name)
        if cached:
            valid = await validate_bot(client, cached)
            cache_entry = _load_cache().get(name, {})
            result[name] = {
                "username": cached,
                "resolved_at": cache_entry.get("resolved_at"),
                "valid": valid,
            }
        else:
            result[name] = {"username": None, "resolved_at": None, "valid": False}
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def async_main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: osint_resolver.py <command> [args]"}))
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "save":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: save <sherlock|cilord> <@username>"}))
            sys.exit(1)
        name = sys.argv[2]
        if name not in ("sherlock", "cilord"):
            print(json.dumps({"error": f"Unknown bot name: {name}. Use 'sherlock' or 'cilord'"}))
            sys.exit(1)
        username = sys.argv[3]
        entry = save_bot(name, username)
        print(json.dumps({"status": "saved", **entry}))
        return

    # Commands below need Telethon
    client = get_telethon_client()
    async with client:
        if cmd == "resolve":
            if len(sys.argv) < 3:
                print(json.dumps({"error": "Usage: resolve <sherlock|cilord>"}))
                sys.exit(1)
            bot_name = sys.argv[2]
            if bot_name == "sherlock":
                result = await resolve_sherlock(client)
            elif bot_name == "cilord":
                result = await resolve_cilord(client)
            else:
                print(json.dumps({"error": f"Unknown bot: {bot_name}"}))
                sys.exit(1)
            print(json.dumps(result, ensure_ascii=False))

        elif cmd == "validate":
            if len(sys.argv) < 3:
                print(json.dumps({"error": "Usage: validate <@username>"}))
                sys.exit(1)
            username = sys.argv[2]
            valid = await validate_bot(client, username)
            print(json.dumps({"username": username, "valid": valid}))

        elif cmd == "status":
            result = await get_status(client)
            print(json.dumps(result, ensure_ascii=False))

        else:
            print(json.dumps({"error": f"Unknown command: {cmd}"}))
            sys.exit(1)


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
