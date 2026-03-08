"""
Bot URL resolver for OSINT skill.

Both Cilordbot and Sherlock Report change their usernames when blocked.
This module resolves current bot usernames using multiple methods:
  1. Personal bot (hardcoded, won't get blocked)
  2. Cache (< 7 days) + validation
  3. HTTP scrape of source website (telelog.org / bit.ly redirect)
  4. Telegram channel (for Sherlock)
  5. Fallback: browser instruction for agent

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

from osint_utils import get_telethon_client

# ---------------------------------------------------------------------------
# Paths & Config
# ---------------------------------------------------------------------------

OSINT_DIR = Path("/workspace/osint")
BOT_URLS_PATH = OSINT_DIR / ".bot_urls.json"
CACHE_MAX_AGE_DAYS = 7

CONFIG_PATH = Path(__file__).parent / "config.json"


def _load_osint_config() -> dict:
    """Load config.json for OSINT skill."""
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


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
    """Validate that a username resolves to a working Telegram bot.

    Uses get_entity() + bot flag check — NO /start sent.
    """
    try:
        entity = await client.get_entity(username)
        return getattr(entity, "bot", False) is True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# HTTP-based resolver (new)
# ---------------------------------------------------------------------------


def _resolve_via_http(urls: list[str]) -> list[str]:
    """Try to resolve bot usernames by scraping source URLs.

    Follows redirects (bit.ly → telelog.org), parses HTML for t.me/ links.
    Returns list of candidate usernames (without @), ordered by priority:
    1. Visible CTA buttons (class="cta-button", not display:none)
    2. Other bot links (ending with "bot")
    3. Any remaining t.me links
    """
    import requests

    candidates = []
    skip_names = {
        "joinchat", "addstickers", "share", "proxy",
        "report_sherlok", "telelog", "telelogs",
    }

    for url in urls:
        try:
            resp = requests.get(
                url,
                timeout=15,
                allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; bot-resolver/1.0)"},
            )
            if resp.status_code != 200:
                continue

            text = resp.text

            # Priority 1: visible CTA buttons (not hidden)
            # Pattern: <a ... href="https://t.me/BOT" class="cta-button">
            # Exclude display:none
            cta_matches = re.findall(
                r'<a[^>]*?href="https?://t\.me/([A-Za-z][A-Za-z0-9_]{3,31})"[^>]*?class="cta-button"',
                text,
            )
            for m in cta_matches:
                if m.lower() not in skip_names and m not in candidates:
                    # Check it's not hidden
                    # Find the full <a> tag and check for display:none
                    tag_match = re.search(
                        rf'<a[^>]*?href="https?://t\.me/{re.escape(m)}"[^>]*?>',
                        text,
                    )
                    if tag_match and 'display:none' not in tag_match.group(0):
                        candidates.append(m)

            # Priority 2: any bot links ending with "bot"
            all_matches = re.findall(r't\.me/([A-Za-z][A-Za-z0-9_]{3,31})', text)
            for m in all_matches:
                if m.lower() not in skip_names and m not in candidates:
                    if m.lower().endswith("bot"):
                        candidates.append(m)

            # Priority 3: remaining links
            for m in all_matches:
                if m.lower() not in skip_names and m not in candidates:
                    candidates.append(m)

            if candidates:
                break  # Got results from this URL

        except Exception:
            continue

    return candidates


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------


async def resolve_sherlock(client) -> dict:
    """Resolve current Sherlock Report bot username.

    Priority:
    1. Personal bot from config (won't get blocked)
    2. Cache (< 7 days) + validate
    3. Telegram channel @report_sherlok — parse last posts for t.me/ links
    4. Fallback: agent should use browser (returned as instruction)
    """
    cfg = _load_osint_config().get("sherlock", {})

    # 0. Personal bot
    personal_bot = cfg.get("personal_bot")
    if personal_bot and not cfg.get("use_resolver", True):
        try:
            entity = await client.get_entity(personal_bot)
            if getattr(entity, "bot", False):
                return {"username": personal_bot, "method": "personal_bot", "valid": True}
        except Exception:
            pass
        print(f"[sherlock] Personal bot {personal_bot} unreachable, falling back to resolver", file=sys.stderr)

    # 1. Cache
    cached = _get_cached("sherlock")
    if cached:
        if await validate_bot(client, cached):
            return {"username": cached, "method": "cache", "valid": True}

    # 2. Telegram channel
    channel_name = cfg.get("channel", "report_sherlok")
    try:
        channel = await client.get_entity(channel_name)
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
    1. Personal bot from config (if set)
    2. Cache (< 7 days) + validate via Telegram
    3. HTTP scrape of source URLs (bit.ly → telelog.org) + validate
    4. Fallback: agent should use browser
    """
    cfg = _load_osint_config().get("cilord", {})

    # 1. Personal bot (if configured)
    personal_bot = cfg.get("personal_bot")
    if personal_bot:
        try:
            entity = await client.get_entity(personal_bot)
            if getattr(entity, "bot", False):
                save_bot("cilord", personal_bot.lstrip("@"))
                return {"username": personal_bot, "method": "personal_bot", "valid": True}
        except Exception:
            print(f"[cilord] Personal bot {personal_bot} unreachable, trying other methods", file=sys.stderr)

    # 2. Cache
    cached = _get_cached("cilord")
    if cached:
        if await validate_bot(client, cached):
            return {"username": cached, "method": "cache", "valid": True}

    # 3. HTTP scrape — resolve from website automatically
    source_urls = cfg.get("source_urls", ["http://bit.ly/4kIt4t9"])
    http_candidates = _resolve_via_http(source_urls)
    for http_username in http_candidates:
        candidate = f"@{http_username}"
        if await validate_bot(client, candidate):
            save_bot("cilord", http_username)
            return {"username": candidate, "method": "http_scrape", "valid": True}
    # If candidates found but none valid
    if http_candidates:
        first = f"@{http_candidates[0]}"
        return {
            "username": first,
            "method": "http_scrape",
            "valid": False,
            "tried": [f"@{c}" for c in http_candidates],
            "warning": f"Found {len(http_candidates)} bots on website but none validated. "
                       "Bots may be temporarily down.",
        }

    # 4. Fallback channel (if configured)
    fallback_channel = cfg.get("fallback_channel")
    if fallback_channel:
        try:
            channel = await client.get_entity(fallback_channel)
            messages = await client.get_messages(channel, limit=5)
            for msg in messages:
                if not msg.text:
                    continue
                matches = re.findall(r"t\.me/(\w+)", msg.text)
                for match in matches:
                    cand = f"@{match}"
                    if await validate_bot(client, cand):
                        save_bot("cilord", match)
                        return {"username": cand, "method": "channel", "valid": True}
        except Exception:
            pass

    # 5. Last resort — browser instruction
    return {
        "username": None,
        "method": "needs_browser",
        "valid": False,
        "instruction": (
            "Could not resolve Cilord bot automatically. "
            f"Source URLs tried: {source_urls}. "
            "Use browser: browser_navigate(URL) → browser_snapshot() → "
            "extract t.me/... bot link. "
            "Then run: python3 osint_resolver.py save cilord @new_bot_username"
        ),
    }


async def get_status(client) -> dict:
    """Get status of both bots."""
    cfg = _load_osint_config()
    result = {}
    for name in ("cilord", "sherlock"):
        bot_cfg = cfg.get(name, {})
        personal = bot_cfg.get("personal_bot")
        cached = _get_cached(name)

        # Check personal bot first
        if personal:
            try:
                entity = await client.get_entity(personal)
                if getattr(entity, "bot", False):
                    result[name] = {
                        "username": personal,
                        "method": "personal_bot",
                        "valid": True,
                    }
                    continue
            except Exception:
                pass

        # Check cached
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
