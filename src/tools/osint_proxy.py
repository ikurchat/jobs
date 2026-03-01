"""
OSINT Proxy Tools — call centralized OSINT server via REST API.

Instead of a separate MCP SSE server (which causes initialization timeout
when combined with setting_sources=["project"]), these tools proxy calls
to the OSINT REST API at http://osint:8400/api/call.

Tools appear as mcp__jobs__osint_* to Claude.
"""

from typing import Any

import httpx
from claude_agent_sdk import tool
from loguru import logger

OSINT_API_URL = "http://osint:8400"
OSINT_TIMEOUT = 120.0


async def _call_osint(tool_name: str, **kwargs: Any) -> dict[str, Any]:
    """Call an OSINT tool via REST API."""
    try:
        async with httpx.AsyncClient(timeout=OSINT_TIMEOUT) as client:
            resp = await client.post(
                f"{OSINT_API_URL}/api/call",
                json={"tool": tool_name, "args": kwargs},
            )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                return _error(data["error"])
            import json
            return _text(json.dumps(data["result"], ensure_ascii=False, indent=2))
    except httpx.ConnectError:
        return _error("OSINT server unavailable (connection refused)")
    except httpx.TimeoutException:
        return _error("OSINT server timeout")
    except Exception as e:
        logger.error(f"OSINT proxy error: {e}")
        return _error(str(e))


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(
    "osint_detect",
    "Detect the type of an OSINT query (phone, fio, email, username, etc.). Free.",
    {"query": str},
)
async def osint_detect(args: dict[str, Any]) -> dict[str, Any]:
    return await _call_osint("osint_detect", query=args["query"])


@tool(
    "osint_cache_check",
    "Check if fresh cached OSINT results exist for a query. Free.",
    {"query_type": str, "query_value": str},
)
async def osint_cache_check(args: dict[str, Any]) -> dict[str, Any]:
    return await _call_osint(
        "osint_cache_check",
        query_type=args["query_type"],
        query_value=args["query_value"],
    )


@tool(
    "osint_spend",
    "Get today's OSINT spend summary (total credits used, query count). Free.",
    {},
)
async def osint_spend(args: dict[str, Any]) -> dict[str, Any]:
    return await _call_osint("osint_spend")


@tool(
    "osint_balance",
    "Check balance of BOTH OSINT bots (Cilordbot and Sherlock Report). Free.",
    {},
)
async def osint_balance(args: dict[str, Any]) -> dict[str, Any]:
    return await _call_osint("osint_balance")


@tool(
    "osint_bot_status",
    "Get status of both OSINT bots (resolved usernames, validity). Free.",
    {},
)
async def osint_bot_status(args: dict[str, Any]) -> dict[str, Any]:
    return await _call_osint("osint_bot_status")


@tool(
    "osint_save_bot",
    "Save/update a resolved bot username (cilord or sherlock). Free.",
    {"bot_name": str, "username": str},
)
async def osint_save_bot(args: dict[str, Any]) -> dict[str, Any]:
    return await _call_osint(
        "osint_save_bot",
        bot_name=args["bot_name"],
        username=args["username"],
    )


@tool(
    "osint_cilord_query",
    "Send a query to Cilordbot. PAID (1 credit). "
    "Use confirmed=false first for preview, then confirmed=true after user confirms.",
    {"query": str, "confirmed": bool},
)
async def osint_cilord_query(args: dict[str, Any]) -> dict[str, Any]:
    return await _call_osint(
        "osint_cilord_query",
        query=args["query"],
        confirmed=args.get("confirmed", False),
    )


@tool(
    "osint_cilord_detail",
    "Get detailed info from a Cilordbot response (groups, channels, messages). Free.",
    {"detail_type": str, "message_id": int, "query_type": str, "query_value": str},
)
async def osint_cilord_detail(args: dict[str, Any]) -> dict[str, Any]:
    return await _call_osint(
        "osint_cilord_detail",
        detail_type=args["detail_type"],
        message_id=args["message_id"],
        query_type=args.get("query_type", ""),
        query_value=args.get("query_value", ""),
    )


@tool(
    "osint_sherlock_query",
    "Send a query to Sherlock Report. PAID (1 credit). "
    "Use confirmed=false first for preview, then confirmed=true after user confirms. "
    "FIO without DOB/phone returns 'needs_more_data' — collect data first. "
    "Use query_type='fio_constructor' as last resort for bare FIO search.",
    {"query_type": str, "query_value": str, "confirmed": bool},
)
async def osint_sherlock_query(args: dict[str, Any]) -> dict[str, Any]:
    return await _call_osint(
        "osint_sherlock_query",
        query_type=args["query_type"],
        query_value=args["query_value"],
        confirmed=args.get("confirmed", False),
    )


@tool(
    "osint_sherlock_setup",
    "Initial setup for Sherlock Report bot (join channel, send /start). Free.",
    {},
)
async def osint_sherlock_setup(args: dict[str, Any]) -> dict[str, Any]:
    return await _call_osint("osint_sherlock_setup")


@tool(
    "osint_sherlock_topup",
    "Navigate to Sherlock Report top-up flow and show tariffs. Free.",
    {},
)
async def osint_sherlock_topup(args: dict[str, Any]) -> dict[str, Any]:
    return await _call_osint("osint_sherlock_topup")


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

OSINT_TOOLS = [
    osint_detect,
    osint_cache_check,
    osint_spend,
    osint_balance,
    osint_bot_status,
    osint_save_bot,
    osint_cilord_query,
    osint_cilord_detail,
    osint_sherlock_query,
    osint_sherlock_setup,
    osint_sherlock_topup,
]

OSINT_TOOL_NAMES = [f"mcp__jobs__{t.name}" for t in OSINT_TOOLS]


def _text(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _error(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": f"Error: {text}"}], "is_error": True}
