"""
Interaction with Sherlock Report — comprehensive OSINT bot.

The bot accepts queries as plain text (no menus):
  phone → searches by phone, FIO → searches by FIO, etc.
It may reply with MULTIPLE messages — collect all of them.

CLI:
  python3 osint_sherlock.py setup
  python3 osint_sherlock.py balance
  python3 osint_sherlock.py query <type> <value>
  python3 osint_sherlock.py topup
"""

import asyncio
import json
import re
import sys
from pathlib import Path

from osint_utils import (
    get_telethon_client,
    wait_for_response,
    wait_for_all_responses,
    click_inline_button,
    save_result,
    is_insufficient_balance,
    parse_balance,
    log_spend,
)
from osint_resolver import resolve_sherlock


MAX_RETRIES = 2
RETRY_TIMEOUTS = [60, 90, 120]
RATE_LIMIT_PAUSE = 30


async def _get_bot_entity(client):
    """Resolve and return the Sherlock bot entity."""
    result = await resolve_sherlock(client)
    if not result.get("valid"):
        return None, result
    entity = await client.get_entity(result["username"])
    return entity, result


async def setup() -> dict:
    """Join the required channel and activate the bot."""
    client = get_telethon_client()
    async with client:
        try:
            from telethon.tl.functions.channels import JoinChannelRequest
            await client(JoinChannelRequest("report_sherlok"))
        except Exception:
            pass

        entity, resolve_result = await _get_bot_entity(client)
        if entity is None:
            return {"status": "error", "error": "bot_not_resolved", "details": resolve_result}

        try:
            last_msgs = await client.get_messages(entity, limit=1)
            after_id = last_msgs[0].id if last_msgs else 0

            await client.send_message(entity, "/start")
            response = await wait_for_response(client, entity, after_id, timeout=15)

            if not response:
                return {"status": "error", "error": "bot_did_not_respond_to_start"}

            # Check for subscription verification button
            if response.reply_markup:
                for keyword in ["проверить подписку", "check subscription", "подписк"]:
                    if await click_inline_button(response, keyword):
                        await asyncio.sleep(3)
                        break

            return {
                "status": "ok",
                "bot": resolve_result["username"],
                "response": response.text or "[no text]",
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}


async def check_balance() -> dict:
    """Check remaining query balance."""
    client = get_telethon_client()
    async with client:
        entity, resolve_result = await _get_bot_entity(client)
        if entity is None:
            return {"status": "error", "error": "bot_not_resolved", "details": resolve_result}

        try:
            last_msgs = await client.get_messages(entity, limit=1)
            after_id = last_msgs[0].id if last_msgs else 0

            # Strategy 1: Click profile/balance button on last message
            clicked = False
            if last_msgs and last_msgs[0].reply_markup:
                for keyword in ["профиль", "profile", "мой профиль", "баланс", "balance"]:
                    if await click_inline_button(last_msgs[0], keyword):
                        clicked = True
                        break

            if not clicked:
                # Strategy 2: Send /start to get fresh keyboard
                await client.send_message(entity, "/start")
                start_response = await wait_for_response(client, entity, after_id, timeout=15)
                if start_response and start_response.reply_markup:
                    after_id = start_response.id
                    for keyword in ["профиль", "profile", "мой профиль", "баланс", "balance"]:
                        if await click_inline_button(start_response, keyword):
                            clicked = True
                            break

                if not clicked:
                    # Strategy 3: Send /profile as last resort
                    await client.send_message(entity, "/profile")

            response = await wait_for_response(client, entity, after_id, timeout=15)
            if not response:
                return {"status": "error", "error": "no_balance_response"}

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
            if balance is not None and balance == 0:
                result["message"] = (
                    "Balance is 0. Top-up needed. "
                    "Rates: 15/$3, 75/$12, 300/$42, 1000/$100"
                )
            if balance is None:
                result["raw_text"] = text
                result["message"] = "Could not parse balance from response. See raw_text."
            return result

        except Exception as e:
            return {"status": "error", "error": str(e)}


async def navigate_topup() -> dict:
    """Navigate to the top-up flow and extract payment info."""
    client = get_telethon_client()
    async with client:
        entity, resolve_result = await _get_bot_entity(client)
        if entity is None:
            return {"status": "error", "error": "bot_not_resolved", "details": resolve_result}

        try:
            last_msgs = await client.get_messages(entity, limit=1)
            after_id = last_msgs[0].id if last_msgs else 0

            # Send /start to get the main menu
            await client.send_message(entity, "/start")
            response = await wait_for_response(client, entity, after_id, timeout=15)

            if not response or not response.reply_markup:
                return {"status": "error", "error": "no_keyboard_on_start"}

            # Look for top-up/payment button
            for keyword in ["пополн", "top up", "оплат", "купить", "buy", "тариф", "rate"]:
                if await click_inline_button(response, keyword):
                    after_id = response.id
                    topup_response = await wait_for_response(client, entity, after_id, timeout=15)
                    if topup_response:
                        buttons_info = []
                        if topup_response.reply_markup and hasattr(topup_response.reply_markup, "rows"):
                            for row in topup_response.reply_markup.rows:
                                for btn in row.buttons:
                                    buttons_info.append(btn.text)
                        return {
                            "status": "ok",
                            "text": topup_response.text or "",
                            "buttons": buttons_info,
                            "bot": resolve_result["username"],
                        }
                    return {"status": "error", "error": "no_topup_response"}

            return {"status": "error", "error": "topup_button_not_found"}

        except Exception as e:
            return {"status": "error", "error": str(e)}


async def send_query(query_type: str, value: str) -> dict:
    """Send a query to Sherlock Report and collect all response messages."""
    client = get_telethon_client()
    async with client:
        entity, resolve_result = await _get_bot_entity(client)
        if entity is None:
            return {"status": "error", "error": "bot_not_resolved", "details": resolve_result}

        for attempt in range(MAX_RETRIES + 1):
            timeout = RETRY_TIMEOUTS[min(attempt, len(RETRY_TIMEOUTS) - 1)]

            try:
                last_msgs = await client.get_messages(entity, limit=1)
                after_id = last_msgs[0].id if last_msgs else 0

                # Send query — photo uses send_file, everything else is text
                if query_type == "photo":
                    file_path = Path(value)
                    if not file_path.exists():
                        return {"status": "error", "error": f"Photo not found: {value}"}
                    await client.send_file(entity, file_path)
                else:
                    await client.send_message(entity, value)

                # Collect ALL responses (bot may send multiple messages)
                responses = await wait_for_all_responses(
                    client, entity, after_id,
                    timeout=timeout,
                    silence_timeout=5,
                )

                if not responses:
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(RATE_LIMIT_PAUSE)
                        continue
                    return {"status": "error", "error": "no_response", "attempt": attempt + 1}

                # Check for insufficient balance
                first_text = responses[0].text or ""
                if is_insufficient_balance(first_text):
                    return {
                        "status": "error",
                        "error": "no_balance",
                        "text": first_text,
                        "message": "Balance depleted. Rates: 15/$3, 75/$12, 300/$42, 1000/$100",
                    }

                # Concatenate all response texts
                full_text = "\n\n".join(r.text for r in responses if r.text)

                path = save_result(query_type, value, "sherlock", "result", full_text)
                log_spend("sherlock", query_type, value)

                return {
                    "status": "ok",
                    "text": full_text,
                    "message_count": len(responses),
                    "path": path,
                    "query_type": query_type,
                    "query_value": value,
                }

            except Exception as e:
                err_str = str(e).lower()
                if "floodwait" in err_str or "flood" in err_str:
                    wait_match = re.search(r"(\d+)", err_str)
                    wait_time = int(wait_match.group(1)) if wait_match else RATE_LIMIT_PAUSE
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(wait_time)
                        continue
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RATE_LIMIT_PAUSE)
                    continue
                return {"status": "error", "error": str(e), "attempt": attempt + 1}

        return {"status": "error", "error": "exhausted_retries"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def async_main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: osint_sherlock.py <setup|balance|query|topup> [args]"}))
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "setup":
        result = await setup()
        print(json.dumps(result, ensure_ascii=False))

    elif cmd == "balance":
        result = await check_balance()
        print(json.dumps(result, ensure_ascii=False))

    elif cmd == "query":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: query <type> <value>"}))
            sys.exit(1)
        query_type = sys.argv[2]
        value = " ".join(sys.argv[3:])
        result = await send_query(query_type, value)
        print(json.dumps(result, ensure_ascii=False))

    elif cmd == "topup":
        result = await navigate_topup()
        print(json.dumps(result, ensure_ascii=False))

    else:
        print(json.dumps({"error": f"Unknown command: {cmd}"}))
        sys.exit(1)


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
