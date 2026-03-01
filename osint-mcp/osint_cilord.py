"""
Interaction with Cilordbot (telelog) — Telegram OSINT bot.

CLI:
  python3 osint_cilord.py send <query>
  python3 osint_cilord.py detail <groups|channels|messages> <message_id> [query_type] [query_value]
  python3 osint_cilord.py balance
"""

import asyncio
import json
import re
import sys

from osint_utils import (
    get_telethon_client,
    acquire_session_lock,
    should_retry,
    wait_for_response,
    wait_for_message_edit,
    click_inline_button,
    save_result,
    detect_query_type,
    is_insufficient_balance,
    is_subscription_required,
    parse_balance,
    log_spend,
)
from osint_resolver import resolve_cilord


# Maps detail type to fuzzy search strings for inline buttons
DETAIL_BUTTON_TEXTS = {
    "groups": ["групп", "group"],
    "channels": ["канал", "channel"],
    "messages": ["сообщ", "messag"],
}

MAX_RETRIES = 2
RETRY_PAUSE = 10


async def _get_bot_entity(client):
    """Resolve and return the Cilord bot entity."""
    result = await resolve_cilord(client)
    if not result.get("valid"):
        return None, result
    entity = await client.get_entity(result["username"])
    return entity, result


async def check_balance() -> dict:
    """Check remaining balance in Cilordbot."""
    client = get_telethon_client()
    async with client:
        entity, resolve_result = await _get_bot_entity(client)
        if entity is None:
            return {"status": "error", "error": "bot_not_resolved", "details": resolve_result}

        try:
            last_msgs = await client.get_messages(entity, limit=1)
            after_id = last_msgs[0].id if last_msgs else 0

            # Strategy 1: Click balance/profile button on last message
            clicked = False
            if last_msgs and last_msgs[0].reply_markup:
                for keyword in ["профиль", "profile", "баланс", "balance", "аккаунт", "account"]:
                    if await click_inline_button(last_msgs[0], keyword):
                        clicked = True
                        break

            if not clicked:
                # Strategy 2: Send /start, look for balance button
                await client.send_message(entity, "/start")
                start_response = await wait_for_response(client, entity, after_id, timeout=15)
                if start_response and start_response.reply_markup:
                    after_id = start_response.id
                    for keyword in ["профиль", "profile", "баланс", "balance"]:
                        if await click_inline_button(start_response, keyword):
                            clicked = True
                            break

                if not clicked:
                    # Strategy 3: Send /profile as last resort
                    await client.send_message(entity, "/profile")

            response = await wait_for_response(client, entity, after_id, timeout=15)
            if not response:
                return {
                    "status": "unknown",
                    "balance": None,
                    "bot": resolve_result["username"],
                    "message": "Could not retrieve balance. Bot did not respond to profile commands.",
                }

            text = response.text or ""
            balance = parse_balance(text)

            # Detect top-up buttons
            topup_available = False
            if response.reply_markup and hasattr(response.reply_markup, "rows"):
                for row in response.reply_markup.rows:
                    for btn in row.buttons:
                        btn_lower = btn.text.lower()
                        if any(kw in btn_lower for kw in ["пополн", "top up", "оплат", "купить", "buy"]):
                            topup_available = True
                            break

            result = {
                "status": "ok",
                "balance": balance,
                "bot": resolve_result["username"],
                "topup_available": topup_available,
            }
            if balance == 0:
                result["message"] = "Balance is 0. Top-up needed."
            if balance is None:
                result["raw_text"] = text
                result["message"] = "Could not parse balance. See raw_text."
            return result

        except Exception as e:
            return {"status": "error", "error": str(e)}


async def send_query(query: str) -> dict:
    """Send a query to Cilordbot, handle captcha, return response."""
    client = get_telethon_client()
    async with client:
        entity, resolve_result = await _get_bot_entity(client)
        if entity is None:
            return {"status": "error", "error": "bot_not_resolved", "details": resolve_result}

        qtype, qvalue = detect_query_type(query)

        for attempt in range(MAX_RETRIES + 1):
            try:
                last_msgs = await client.get_messages(entity, limit=1)
                after_id = last_msgs[0].id if last_msgs else 0

                await client.send_message(entity, query)

                response = await wait_for_response(client, entity, after_id, timeout=30)
                if not response:
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(RETRY_PAUSE)
                        continue
                    return {"status": "error", "error": "no_response", "attempt": attempt + 1}

                # Check for insufficient balance
                text = response.text or "[no text]"
                if is_insufficient_balance(text):
                    return {
                        "status": "error",
                        "error": "no_balance",
                        "text": text,
                        "bot": resolve_result.get("username"),
                    }

                # Check for subscription requirement
                if is_subscription_required(text):
                    return {
                        "status": "error",
                        "error": "subscription_required",
                        "text": text,
                        "bot": resolve_result.get("username"),
                        "message": "Bot requires channel subscription. Subscribe and retry.",
                    }

                # Check for captcha button
                captcha_clicked = False
                if response.reply_markup:
                    for keyword in ["click", "нажм", "button", "кнопк"]:
                        if await click_inline_button(response, keyword):
                            captcha_clicked = True
                            break

                if captcha_clicked:
                    post_captcha = await wait_for_response(
                        client, entity, response.id, timeout=30
                    )
                    if post_captcha:
                        response = post_captcha
                        text = response.text or "[no text]"

                path = save_result(qtype, qvalue, "cilord", "basic", text)
                log_spend("cilord", qtype, qvalue)

                return {
                    "status": "ok",
                    "message_id": response.id,
                    "text": text,
                    "path": path,
                    "query_type": qtype,
                    "query_value": qvalue,
                }

            except Exception as e:
                retry, pause = should_retry(e, attempt, MAX_RETRIES, RETRY_PAUSE)
                if retry:
                    await asyncio.sleep(pause)
                    continue
                return {"status": "error", "error": str(e), "attempt": attempt + 1}

        return {"status": "error", "error": "exhausted_retries"}


async def _wait_for_edit_or_new(
    client, entity, message_id: int,
    original_text: str = "",
    original_edit_date=None,
    timeout: int = 20,
    poll_interval: int = 2,
):
    """Single polling loop that checks both message edit and new incoming message.

    Returns the first result found (edited message or new message), or None.
    """
    import time
    bot_id = getattr(entity, "id", None)
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Check edit
        msg = await client.get_messages(entity, ids=message_id)
        if msg:
            if msg.edit_date != original_edit_date or (msg.text or "") != (original_text or ""):
                return msg
        # Check new message
        messages = await client.get_messages(entity, limit=5)
        for m in messages:
            if m.id > message_id and not getattr(m, "out", False):
                sender_id = getattr(m, "sender_id", None)
                if sender_id == bot_id:
                    return m
        await asyncio.sleep(poll_interval)
    return None


async def get_detail(
    detail_type: str,
    message_id: int,
    query_type: str | None = None,
    query_value: str | None = None,
) -> dict:
    """Click a detail inline button and collect the response.

    detail_type: one of 'groups', 'channels', 'messages'
    message_id: the ID of the message with inline buttons
    query_type/query_value: for correct cache directory naming
    """
    if detail_type not in DETAIL_BUTTON_TEXTS:
        return {"status": "error", "error": f"Unknown detail type: {detail_type}"}

    client = get_telethon_client()
    async with client:
        entity, resolve_result = await _get_bot_entity(client)
        if entity is None:
            return {"status": "error", "error": "bot_not_resolved", "details": resolve_result}

        try:
            msg = await client.get_messages(entity, ids=message_id)
            if not msg:
                return {"status": "error", "error": f"Message {message_id} not found"}

            # Capture state BEFORE clicking (race condition fix)
            original_text = msg.text or ""
            original_edit_date = msg.edit_date

            # If caller didn't provide query context, try to detect from message
            if not query_type or not query_value:
                qtype, qvalue = detect_query_type(original_text)
                if qtype == "unknown":
                    query_type = query_type or "query"
                    query_value = query_value or str(message_id)
                else:
                    query_type = qtype
                    query_value = qvalue

            # Try to click the right button
            clicked = False
            for keyword in DETAIL_BUTTON_TEXTS[detail_type]:
                if await click_inline_button(msg, keyword):
                    clicked = True
                    break

            if not clicked:
                buttons_text = []
                if msg.reply_markup and hasattr(msg.reply_markup, "rows"):
                    for row in msg.reply_markup.rows:
                        for btn in row.buttons:
                            buttons_text.append(btn.text)
                return {
                    "status": "error",
                    "error": "button_not_found",
                    "detail_type": detail_type,
                    "available_buttons": buttons_text,
                }

            # Wait for response — single loop checks BOTH edit and new message
            # (avoids two parallel tasks doubling API calls)
            result_msg = await _wait_for_edit_or_new(
                client, entity, message_id,
                original_text=original_text,
                original_edit_date=original_edit_date,
                timeout=20,
            )

            if not result_msg:
                return {"status": "error", "error": "no_detail_response"}

            text = result_msg.text or "[no text]"
            path = save_result(query_type, query_value, "cilord", detail_type, text)

            return {
                "status": "ok",
                "text": text,
                "path": path,
                "message_id": result_msg.id,
            }

        except Exception as e:
            return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def async_main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: osint_cilord.py <send|detail|balance> [args]"}))
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "send":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: send <query>"}))
            sys.exit(1)
        query = " ".join(sys.argv[2:])
        result = await send_query(query)
        print(json.dumps(result, ensure_ascii=False))

    elif cmd == "detail":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: detail <groups|channels|messages> <message_id> [query_type] [query_value]"}))
            sys.exit(1)
        detail_type = sys.argv[2]
        try:
            message_id = int(sys.argv[3])
        except ValueError:
            print(json.dumps({"error": f"Invalid message_id: {sys.argv[3]}"}))
            sys.exit(1)
        qt = sys.argv[4] if len(sys.argv) > 4 else None
        qv = sys.argv[5] if len(sys.argv) > 5 else None
        result = await get_detail(detail_type, message_id, qt, qv)
        print(json.dumps(result, ensure_ascii=False))

    elif cmd == "balance":
        result = await check_balance()
        print(json.dumps(result, ensure_ascii=False))

    else:
        print(json.dumps({"error": f"Unknown command: {cmd}"}))
        sys.exit(1)


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
