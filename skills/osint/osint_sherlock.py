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
    acquire_session_lock,
    should_retry,
    wait_for_response,
    wait_for_all_responses,
    wait_for_message_edit,
    click_inline_button,
    click_by_callback_data,
    save_result,
    is_insufficient_balance,
    is_subscription_required,
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


# Constructor field -> callback data mapping
_CONSTRUCTOR_FIELDS = {
    "lastname": "constructor/lastname",
    "firstname": "constructor/firstname",
    "middlename": "constructor/middlename",
    "day": "constructor/day",
    "month": "constructor/month",
    "year": "constructor/year",
}


async def _fill_constructor_field(client, entity, constructor_msg, field_data: str, value: str, timeout=10):
    """Click a constructor field by callback data, wait for prompt, send value, wait for update.

    Uses callback data (e.g. 'constructor/lastname') instead of button text because
    filled fields show '✔ VALUE' instead of the original label.
    """
    old_edit = constructor_msg.edit_date
    old_text = constructor_msg.text or ""
    clicked = await click_by_callback_data(constructor_msg, field_data)
    if not clicked:
        return constructor_msg

    # Wait for "Введите ..." prompt (poll edit, up to 5s)
    prompt_deadline = asyncio.get_event_loop().time() + 5
    prompt_received = False
    while asyncio.get_event_loop().time() < prompt_deadline:
        check = await client.get_messages(entity, ids=constructor_msg.id)
        if check and (check.edit_date != old_edit or (check.text or "") != old_text):
            prompt_received = True
            old_edit = check.edit_date
            break
        await asyncio.sleep(0.5)
    if not prompt_received:
        await asyncio.sleep(2)

    # Send the value
    await client.send_message(entity, value)
    # Wait for constructor to update with ✔
    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < timeout:
        updated = await client.get_messages(entity, ids=constructor_msg.id)
        if updated and updated.edit_date != old_edit:
            return updated
        await asyncio.sleep(1)
    return constructor_msg


def _parse_fio(value: str) -> dict:
    """Parse FIO string into components: lastname, firstname, middlename, date parts."""
    parts = value.strip().split()
    result = {}
    # Check if last part is a date DD.MM.YYYY
    if parts and re.match(r"\d{2}\.\d{2}\.\d{4}$", parts[-1]):
        date_str = parts.pop()
        day, month, year = date_str.split(".")
        result["day"] = day
        result["month"] = month
        result["year"] = year
    # Check if last part is just a year YYYY
    elif parts and re.match(r"\d{4}$", parts[-1]):
        result["year"] = parts.pop()

    if len(parts) >= 1:
        result["lastname"] = parts[0]
    if len(parts) >= 2:
        result["firstname"] = parts[1]
    if len(parts) >= 3:
        result["middlename"] = parts[2]
    return result


async def _collect_constructor_pages(client, entity, msg_id: int, max_pages: int = 30) -> list[dict]:
    """Collect all paginated constructor results.

    Each page has one entry: `ФИО ДД.ММ.ГГГГ` + age + birthplace.
    Returns list of dicts: [{fio_date, age, birthplace, raw_text}, ...]
    """
    entries = []
    seen_pages = set()

    for _ in range(max_pages):
        msg = await client.get_messages(entity, ids=msg_id)
        if not msg or not msg.text:
            break

        text = msg.text
        # Detect if this is a results page (has the copy instruction)
        if "скопируйте" not in text.lower() and "досье" not in text.lower():
            break

        # Parse current page
        fio_match = re.search(r"`([^`]+\d{2}\.\d{2}\.\d{4})`", text)
        if fio_match:
            fio_date = fio_match.group(1)
            if fio_date in seen_pages:
                break  # looped back
            seen_pages.add(fio_date)

            age_match = re.search(r"\*\*Возраст:\*\*\s*(.+)", text)
            place_match = re.search(r"\*\*Место рождения:\*\*\s*(.+)", text)
            entries.append({
                "fio_date": fio_date,
                "age": age_match.group(1).strip() if age_match else None,
                "birthplace": place_match.group(1).strip() if place_match else None,
                "raw_text": text,
            })

        # Find and click next page button (⮕)
        next_clicked = False
        if msg.reply_markup and hasattr(msg.reply_markup, "rows"):
            for ri, row in enumerate(msg.reply_markup.rows):
                for ci, btn in enumerate(row.buttons):
                    data = getattr(btn, "data", None)
                    if data and b"constructor/view" in data and "⮕" in btn.text:
                        await msg.click(ri, ci)
                        next_clicked = True
                        break
                if next_clicked:
                    break

        if not next_clicked:
            break  # last page

        await asyncio.sleep(1.5)

    return entries


async def _fio_via_constructor(client, entity, fio_parts: dict) -> dict:
    """Search FIO via Sherlock's constructor (for partial data / no birth date).

    Flow:
    1. Open constructor (click data=constructor or send /start first)
    2. Reset stale fields (click data=constructor/reset)
    3. Fill fields by callback data (constructor/lastname, etc.)
    4. Click search (constructor/search)
    5. Collect all paginated results

    Returns dict with found entries or error.
    """
    # Get last message and try to open constructor
    last_msgs = await client.get_messages(entity, limit=3)
    if not last_msgs:
        return {"status": "error", "error": "no_messages"}

    # Find a message with the constructor button (data=constructor)
    constructor_opened = False
    msg = None
    for m in last_msgs:
        if await click_by_callback_data(m, "constructor"):
            msg = m
            constructor_opened = True
            break

    if not constructor_opened:
        # Send /start to get fresh menu
        after_id = last_msgs[0].id
        await client.send_message(entity, "/start")
        # /start sends multiple messages — wait for the menu one
        await asyncio.sleep(3)
        new_msgs = await client.get_messages(entity, limit=5)
        for m in new_msgs:
            if m.id > after_id and not getattr(m, "out", False):
                if await click_by_callback_data(m, "constructor"):
                    msg = m
                    constructor_opened = True
                    break

    if not constructor_opened:
        return {"status": "error", "error": "constructor_button_not_found"}

    # Wait for constructor to appear (message edit)
    await asyncio.sleep(2)
    constructor_msg = await client.get_messages(entity, ids=msg.id)
    if not constructor_msg:
        return {"status": "error", "error": "constructor_not_opened"}

    # Reset stale fields from previous searches
    old_edit = constructor_msg.edit_date
    await click_by_callback_data(constructor_msg, "constructor/reset")
    # Wait for reset to complete
    for _ in range(6):
        await asyncio.sleep(0.5)
        constructor_msg = await client.get_messages(entity, ids=msg.id)
        if constructor_msg and constructor_msg.edit_date != old_edit:
            break

    # Fill fields using callback data
    for key, cb_data in _CONSTRUCTOR_FIELDS.items():
        if key in fio_parts and fio_parts[key]:
            constructor_msg = await _fill_constructor_field(
                client, entity, constructor_msg, cb_data, fio_parts[key]
            )

    # Click search
    old_edit = constructor_msg.edit_date
    await click_by_callback_data(constructor_msg, "constructor/search")

    # Wait for results (message edits to show first result page)
    for _ in range(10):
        await asyncio.sleep(1)
        result_msg = await client.get_messages(entity, ids=constructor_msg.id)
        if result_msg and result_msg.edit_date != old_edit:
            break
    else:
        result_msg = await client.get_messages(entity, ids=constructor_msg.id)

    result_text = result_msg.text if result_msg else ""

    if not result_text or "указать любое количество" in result_text:
        return {"status": "error", "error": "no_results", "text": result_text}

    # Collect all pages
    entries = await _collect_constructor_pages(client, entity, constructor_msg.id)

    # Format entries as simple strings for backward compat
    entry_strings = [e["fio_date"] for e in entries]

    return {
        "status": "ok",
        "phase": "constructor_results",
        "entries": entry_strings,
        "entries_detail": entries,
        "total": len(entries),
        "raw_text": result_text,
        "message": (
            f"Constructor found {len(entries)} matches. Send the full FIO+date "
            "as a regular query to get the complete dossier."
        ) if entries else "No matches found in constructor.",
        "constructor_msg_id": constructor_msg.id,
    }


async def send_query(query_type: str, value: str) -> dict:
    """Send a query to Sherlock Report and collect all response messages."""
    client = get_telethon_client()
    async with client:
        entity, resolve_result = await _get_bot_entity(client)
        if entity is None:
            return {"status": "error", "error": "bot_not_resolved", "details": resolve_result}

        # FIO validation gate — block bare FIO without DOB or phone
        if query_type == "fio" and not re.search(r"\d{2}\.\d{2}\.\d{4}", value):
            if not re.search(r"[78]\d{10}", value):
                return {
                    "status": "blocked",
                    "phase": "needs_more_data",
                    "query_type": query_type,
                    "query_value": value,
                    "message": "FIO without DOB/phone blocked. Use fio_constructor as last resort.",
                }

        # fio_constructor — explicit path via constructor (last resort)
        if query_type == "fio_constructor":
            fio_parts = _parse_fio(value)
            constructor_result = await _fio_via_constructor(client, entity, fio_parts)

            if constructor_result.get("status") != "ok" or not constructor_result.get("entries"):
                log_spend("sherlock", query_type, value)
                return constructor_result

            entries = constructor_result["entries"]
            if len(entries) == 1:
                value = entries[0]
                query_type = "fio"
                await asyncio.sleep(2)
            else:
                log_spend("sherlock", query_type, value)
                return constructor_result

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
                    silence_timeout=15,
                )

                if not responses:
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(RATE_LIMIT_PAUSE)
                        continue
                    return {"status": "error", "error": "no_response", "attempt": attempt + 1}

                # Handle country selection menu (FIO+date → Россия/Казахстан/...)
                country_clicked = False
                for resp in responses:
                    if resp.reply_markup and hasattr(resp.reply_markup, "rows"):
                        for row in resp.reply_markup.rows:
                            for btn in row.buttons:
                                data = getattr(btn, "data", None)
                                if data and b"PERSON/" in (data if isinstance(data, bytes) else data.encode()):
                                    # Found country menu — click Россия (PERSON/RU/)
                                    ru_clicked = await click_inline_button(resp, "Россия")
                                    if not ru_clicked:
                                        # Fallback: click first PERSON/ button (skip "Назад" etc.)
                                        for fi, frow in enumerate(resp.reply_markup.rows):
                                            for fj, fbtn in enumerate(frow.buttons):
                                                fdata = getattr(fbtn, "data", None)
                                                if fdata and b"PERSON/" in (fdata if isinstance(fdata, bytes) else fdata.encode()):
                                                    await resp.click(fi, fj)
                                                    ru_clicked = True
                                                    break
                                            if ru_clicked:
                                                break
                                    country_clicked = True
                                    break
                            if country_clicked:
                                break
                    if country_clicked:
                        break

                if country_clicked:
                    # After country selection, wait for the actual search results
                    latest_id = max(r.id for r in responses)
                    search_responses = await wait_for_all_responses(
                        client, entity, latest_id,
                        timeout=max(timeout - 15, 60),
                        silence_timeout=15,
                    )
                    if search_responses:
                        responses = search_responses
                    else:
                        # Check if the country menu message was edited with results
                        for resp in responses:
                            edited = await wait_for_message_edit(
                                client, entity, resp.id,
                                timeout=30,
                                original_text=resp.text,
                                original_edit_date=resp.edit_date,
                            )
                            if edited and edited.text and edited.text != (resp.text or ""):
                                responses = [edited]
                                break

                # Check ALL messages for balance errors, not just the first
                for resp in responses:
                    resp_text = resp.text or ""
                    if is_insufficient_balance(resp_text):
                        return {
                            "status": "error",
                            "error": "no_balance",
                            "text": resp_text,
                            "message": "Balance depleted. Rates: 15/$3, 75/$12, 300/$42, 1000/$100",
                        }

                # Check for subscription requirement
                for resp in responses:
                    resp_text = resp.text or ""
                    if is_subscription_required(resp_text):
                        return {
                            "status": "error",
                            "error": "subscription_required",
                            "text": resp_text,
                            "message": "Bot requires channel subscription. Subscribe and retry.",
                        }

                # If first message is "searching..." placeholder, wait for edit
                first_text = responses[0].text or ""
                _search_placeholders = ["идёт поиск", "выполняется поиск", "подождите", "ищу", "searching"]
                if len(first_text) < 200 and any(kw in first_text.lower() for kw in _search_placeholders):
                    edited = await wait_for_message_edit(
                        client, entity, responses[0].id,
                        timeout=max(timeout - 15, 30),
                        original_text=first_text,
                        original_edit_date=responses[0].edit_date,
                    )
                    if edited and edited.text and edited.text != first_text:
                        responses[0] = edited
                    # Also collect any new messages that appeared during the wait
                    latest_id = max(r.id for r in responses)
                    extra = await wait_for_all_responses(
                        client, entity, latest_id,
                        timeout=15,
                        silence_timeout=8,
                    )
                    # Deduplicate by message id
                    seen_ids = {r.id for r in responses}
                    responses.extend(r for r in extra if r.id not in seen_ids)

                # Concatenate all response texts
                full_text = "\n\n".join(r.text for r in responses if r.text)

                # Extract inline button URLs (report link, messengers, etc.)
                urls = {}
                for resp in responses:
                    if resp.reply_markup and hasattr(resp.reply_markup, "rows"):
                        for row in resp.reply_markup.rows:
                            for btn in row.buttons:
                                if hasattr(btn, "url") and btn.url:
                                    btn_text = btn.text.strip()
                                    if "отчет" in btn_text.lower() or "report" in btn_text.lower():
                                        urls["report_url"] = btn.url
                                    elif "telegram" in btn_text.lower():
                                        urls["telegram_url"] = btn.url
                                    elif "whatsapp" in btn_text.lower():
                                        urls["whatsapp_url"] = btn.url
                                    else:
                                        urls.setdefault("other_urls", []).append(
                                            {"text": btn_text, "url": btn.url}
                                        )

                path = save_result(query_type, value, "sherlock", "result", full_text)
                log_spend("sherlock", query_type, value)

                result = {
                    "status": "ok",
                    "text": full_text,
                    "message_count": len(responses),
                    "path": path,
                    "query_type": query_type,
                    "query_value": value,
                }
                if urls:
                    result.update(urls)
                return result

            except Exception as e:
                retry, pause = should_retry(e, attempt, MAX_RETRIES, RATE_LIMIT_PAUSE)
                if retry:
                    await asyncio.sleep(pause)
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
