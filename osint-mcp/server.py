"""
OSINT MCP SSE Server — centralized Telegram OSINT tools.

11 tools exposed via MCP protocol over SSE transport.
asyncio.Lock serializes all Telethon operations to prevent
rate limits and session conflicts.

Run: python -m server
"""

import asyncio
import json
import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, Mount

from osint_utils import detect_query_type, check_cache, get_daily_spend
from osint_resolver import save_bot, get_status
from osint_cilord import (
    check_balance as cilord_check_balance,
    send_query as cilord_send_query,
    get_detail as cilord_get_detail,
)
from osint_sherlock import (
    setup as sherlock_setup,
    check_balance as sherlock_check_balance,
    navigate_topup as sherlock_navigate_topup,
    send_query as sherlock_send_query,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("osint-mcp")

# Global lock — serializes ALL Telethon operations
_telethon_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "osint",
    host="0.0.0.0",
    port=8400,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


@mcp.tool()
async def osint_detect(query: str) -> str:
    """Detect the type of an OSINT query (phone, fio, email, username, etc.).

    Returns JSON with query_type and normalized query_value.
    Free (no credits spent).
    """
    qtype, qvalue = detect_query_type(query)
    return json.dumps({"query_type": qtype, "query_value": qvalue}, ensure_ascii=False)


@mcp.tool()
async def osint_cache_check(query_type: str, query_value: str) -> str:
    """Check if fresh cached OSINT results exist for a query.

    Returns JSON with cached (bool), path, age_hours.
    Free (no credits spent).
    """
    result = check_cache(query_type, query_value)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def osint_spend() -> str:
    """Get today's OSINT spend summary (total credits used, query count).

    Free (no credits spent).
    """
    result = get_daily_spend()
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def osint_balance() -> str:
    """Check balance of BOTH OSINT bots (Cilordbot and Sherlock Report).

    Requires Telethon session. Serialized via lock.
    Free (no credits spent).
    """
    async with _telethon_lock:
        cilord_result = await cilord_check_balance()
        sherlock_result = await sherlock_check_balance()
    return json.dumps({
        "cilord": cilord_result,
        "sherlock": sherlock_result,
    }, ensure_ascii=False)


@mcp.tool()
async def osint_bot_status() -> str:
    """Get status of both OSINT bots (resolved usernames, validity).

    Requires Telethon session. Serialized via lock.
    Free (no credits spent).
    """
    from osint_utils import get_telethon_client
    async with _telethon_lock:
        client = get_telethon_client()
        async with client:
            result = await get_status(client)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def osint_save_bot(bot_name: str, username: str) -> str:
    """Save/update a resolved bot username (cilord or sherlock).

    Use after manually resolving a bot via browser.
    Free (no credits spent).

    Args:
        bot_name: "cilord" or "sherlock"
        username: Bot username (e.g. "@CilordBot")
    """
    if bot_name not in ("cilord", "sherlock"):
        return json.dumps({"error": f"Unknown bot: {bot_name}. Use 'cilord' or 'sherlock'"})
    entry = save_bot(bot_name, username)
    return json.dumps({"status": "saved", **entry}, ensure_ascii=False)


# Query types supported by each bot
CILORD_SUPPORTED_TYPES = {"phone", "username"}
SHERLOCK_SUPPORTED_TYPES = {
    "phone", "fio", "fio_constructor", "email", "username", "auto_plate", "auto_vin",
    "social", "document", "address", "cadastre", "ogrn", "domain_ip", "photo",
}


@mcp.tool()
async def osint_cilord_query(query: str, confirmed: bool = False) -> str:
    """Send a query to Cilordbot (PAID — costs 1 credit per query).

    Two-phase approach:
    - confirmed=false: returns query type, cache status, estimated cost (NO credit spent)
    - confirmed=true: actually sends the query to the bot (SPENDS credit)

    Cilordbot supports: phone, username. For other types (fio, email, etc.)
    returns skip status — use osint_sherlock_query instead.

    ALWAYS call with confirmed=false first, show the preview to the user,
    get explicit confirmation, then call with confirmed=true.

    Args:
        query: The search query (phone, username, etc.)
        confirmed: Set to true only after user confirms the paid query
    """
    qtype, qvalue = detect_query_type(query)

    # Skip unsupported query types early
    if qtype not in CILORD_SUPPORTED_TYPES:
        return json.dumps({
            "status": "skipped",
            "reason": "unsupported_query_type",
            "query_type": qtype,
            "query_value": qvalue,
            "message": f"Cilordbot does not support '{qtype}' queries. Use osint_sherlock_query instead.",
        }, ensure_ascii=False)

    if not confirmed:
        cache = check_cache(qtype, qvalue)
        spend = get_daily_spend()
        return json.dumps({
            "phase": "preview",
            "query_type": qtype,
            "query_value": qvalue,
            "cached": cache["cached"],
            "cache_path": cache["path"],
            "cache_age_hours": cache["age_hours"],
            "today_spend": spend["total_credits"],
            "estimated_cost": 1,
            "message": "Call again with confirmed=true to execute (costs 1 credit)."
                       + (" Fresh cache available — consider using cached results." if cache["cached"] else ""),
        }, ensure_ascii=False)

    async with _telethon_lock:
        result = await cilord_send_query(query)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def osint_cilord_detail(
    detail_type: str,
    message_id: int,
    query_type: str = "",
    query_value: str = "",
) -> str:
    """Get detailed info from a Cilordbot response (groups, channels, or messages).

    Clicks an inline button on a previous Cilord response message.
    Free (no additional credits spent).

    Args:
        detail_type: One of "groups", "channels", "messages"
        message_id: The Telegram message ID from osint_cilord_query result
        query_type: Original query type (for cache naming)
        query_value: Original query value (for cache naming)
    """
    async with _telethon_lock:
        result = await cilord_get_detail(
            detail_type, message_id,
            query_type or None, query_value or None,
        )
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def osint_sherlock_query(
    query_type: str,
    query_value: str,
    confirmed: bool = False,
) -> str:
    """Send a query to Sherlock Report (PAID — costs 1 credit per query).

    Two-phase approach:
    - confirmed=false: returns cache status, estimated cost (NO credit spent).
      For FIO without DOB/phone returns "phase": "needs_more_data" — collect
      DOB or phone before proceeding.
    - confirmed=true: actually sends the query (SPENDS credit).
      FIO without DOB/phone is blocked ("status": "blocked").

    Use query_type="fio_constructor" as last resort to search FIO via Sherlock's
    constructor without DOB (costs 1 credit, may return multiple matches).

    ALWAYS call with confirmed=false first, show the preview to the user,
    get explicit confirmation, then call with confirmed=true.

    Args:
        query_type: Type of query (phone, fio, fio_constructor, email, username, auto_plate, etc.)
        query_value: The search value
        confirmed: Set to true only after user confirms the paid query
    """
    import re as _re

    if not confirmed:
        # FIO without DOB/phone → needs_more_data (hard gate at preview)
        if query_type == "fio" and not _re.search(r"\d{2}\.\d{2}\.\d{4}", query_value):
            if not _re.search(r"[78]\d{10}", query_value):
                spend = get_daily_spend()
                return json.dumps({
                    "phase": "needs_more_data",
                    "query_type": query_type,
                    "query_value": query_value,
                    "today_spend": spend["total_credits"],
                    "message": (
                        "ФИО без даты рождения или телефона — недостаточно для точного поиска. "
                        "Сначала уточните у пользователя ДР/телефон/тг-логин, "
                        "или найдите ДР через веб-поиск. "
                        "Крайний случай: query_type=fio_constructor (менее точно, тратит кредит)."
                    ),
                }, ensure_ascii=False)

        cache = check_cache(query_type, query_value)
        spend = get_daily_spend()
        msg = "Call again with confirmed=true to execute (costs 1 credit)."
        if cache["cached"]:
            msg += " Fresh cache available — consider using cached results."

        # FIO-specific hints
        hints = []
        if query_type == "fio":
            hints.append("Поиск только по ФИО может дать несколько совпадений.")
        if query_type == "fio_constructor":
            hints.append("Конструктор — менее точный метод. Может вернуть несколько совпадений или 0.")

        result = {
            "phase": "preview",
            "query_type": query_type,
            "query_value": query_value,
            "cached": cache["cached"],
            "cache_path": cache["path"],
            "cache_age_hours": cache["age_hours"],
            "today_spend": spend["total_credits"],
            "estimated_cost": 1,
            "message": msg,
        }
        if hints:
            result["hints"] = hints
        return json.dumps(result, ensure_ascii=False)

    # Confirmed phase — block bare FIO without DOB/phone
    if query_type == "fio" and not _re.search(r"\d{2}\.\d{2}\.\d{4}", query_value):
        if not _re.search(r"[78]\d{10}", query_value):
            return json.dumps({
                "status": "blocked",
                "phase": "needs_more_data",
                "query_type": query_type,
                "query_value": query_value,
                "message": "FIO without DOB/phone blocked. Use fio_constructor as last resort.",
            }, ensure_ascii=False)

    async with _telethon_lock:
        result = await sherlock_send_query(query_type, query_value)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def osint_sherlock_setup() -> str:
    """Initial setup for Sherlock Report bot (join channel, send /start).

    Run once before first use. Free (no credits spent).
    """
    async with _telethon_lock:
        result = await sherlock_setup()
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def osint_sherlock_topup() -> str:
    """Navigate to Sherlock Report top-up flow and show tariffs.

    Returns available tariff buttons and payment info.
    Free (no credits spent).
    """
    async with _telethon_lock:
        result = await sherlock_navigate_topup()
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# REST API — lightweight alternative to MCP SSE for proxy clients
# ---------------------------------------------------------------------------

_TOOL_MAP = {
    "osint_detect": osint_detect,
    "osint_cache_check": osint_cache_check,
    "osint_spend": osint_spend,
    "osint_balance": osint_balance,
    "osint_bot_status": osint_bot_status,
    "osint_save_bot": osint_save_bot,
    "osint_cilord_query": osint_cilord_query,
    "osint_cilord_detail": osint_cilord_detail,
    "osint_sherlock_query": osint_sherlock_query,
    "osint_sherlock_setup": osint_sherlock_setup,
    "osint_sherlock_topup": osint_sherlock_topup,
}


async def api_call(request):
    """REST endpoint: POST /api/call {"tool": "...", "args": {...}}."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    tool_name = body.get("tool")
    args = body.get("args", {})

    if tool_name not in _TOOL_MAP:
        return JSONResponse({"error": f"Unknown tool: {tool_name}"}, status_code=404)

    try:
        result_str = await _TOOL_MAP[tool_name](**args)
        return JSONResponse({"result": json.loads(result_str)})
    except Exception as e:
        logger.exception(f"REST API error calling {tool_name}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_tools(request):
    """GET /api/tools — list available tools."""
    return JSONResponse({"tools": sorted(_TOOL_MAP.keys())})


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

async def health(request):
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# ASGI app: Starlette + MCP SSE + REST API
# ---------------------------------------------------------------------------

def create_app() -> Starlette:
    """Create Starlette ASGI app with health check, REST API, and MCP SSE routes."""
    sse_app = mcp.sse_app()

    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/api/call", api_call, methods=["POST"]),
        Route("/api/tools", api_tools, methods=["GET"]),
        Mount("/", app=sse_app),
    ]

    return Starlette(routes=routes)


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8400,
        log_level="info",
    )
