"""Debug: fill constructor fields and search."""
import asyncio
import json
import time

from osint_utils import get_telethon_client, click_inline_button
from osint_resolver import resolve_sherlock


async def click_and_wait(client, entity, msg, button_text, timeout=10):
    """Click a button and wait for edit."""
    old_text = msg.text
    old_edit = msg.edit_date
    await click_inline_button(msg, button_text)

    start = time.time()
    while time.time() - start < timeout:
        updated = await client.get_messages(entity, ids=msg.id)
        if updated and (updated.text != old_text or updated.edit_date != old_edit):
            return updated
        await asyncio.sleep(1)
    return None


def print_buttons(msg):
    if msg.reply_markup and hasattr(msg.reply_markup, "rows"):
        for ri, row in enumerate(msg.reply_markup.rows):
            for bi, btn in enumerate(row.buttons):
                btn_text = getattr(btn, "text", "")
                btn_data = getattr(btn, "data", None)
                print(f"  [{ri}][{bi}]: {btn_text!r} data={btn_data!r}")


async def main():
    client = get_telethon_client()
    async with client:
        result = await resolve_sherlock(client)
        print(f"Bot: {result['username']}")
        entity = await client.get_entity(result["username"])

        # Get last message (should be constructor from previous debug)
        msgs = await client.get_messages(entity, limit=3)

        # Find message with constructor buttons
        constructor_msg = None
        for m in msgs:
            if m.reply_markup and hasattr(m.reply_markup, "rows"):
                for row in m.reply_markup.rows:
                    for btn in row.buttons:
                        if getattr(btn, "data", b"") == b"constructor/lastname":
                            constructor_msg = m
                            break

        if not constructor_msg:
            print("Constructor not found, clicking 'Поиск по неполным данным' first...")
            last = msgs[0]
            clicked = await click_inline_button(last, "неполным данным")
            if not clicked:
                await client.send_message(entity, "/start")
                await asyncio.sleep(3)
                last = (await client.get_messages(entity, limit=1))[0]
                await click_inline_button(last, "неполным данным")
            await asyncio.sleep(3)
            constructor_msg = (await client.get_messages(entity, ids=last.id))

        print(f"\nConstructor message #{constructor_msg.id}")
        print(f"Text: {constructor_msg.text!r}")
        print_buttons(constructor_msg)

        # Step 1: Click "Фамилия"
        print("\n--- Step 1: Click 'Фамилия' ---")
        updated = await click_and_wait(client, entity, constructor_msg, "Фамилия")
        if updated:
            print(f"After click: {updated.text!r}")
            print_buttons(updated)
            constructor_msg = updated
        else:
            print("No edit after clicking Фамилия")
            # Maybe bot expects text input after clicking?
            # Let's check recent messages
            recent = await client.get_messages(entity, limit=3)
            for m in recent:
                if m.id > constructor_msg.id and not m.out:
                    print(f"  New msg #{m.id}: {m.text!r}")

        # Step 2: Send surname
        print("\n--- Step 2: Sending 'Ткаченко' ---")
        after_id = (await client.get_messages(entity, limit=1))[0].id
        await client.send_message(entity, "Ткаченко")
        await asyncio.sleep(5)

        # Check what happened
        msgs = await client.get_messages(entity, limit=5)
        for m in msgs:
            if not m.out and m.id > after_id - 2:
                print(f"\nMessage #{m.id}:")
                print(f"  Text: {(m.text or '')[:200]!r}")
                print_buttons(m)

        # Check if constructor message was edited
        latest = await client.get_messages(entity, ids=constructor_msg.id)
        if latest and latest.text != constructor_msg.text:
            print(f"\nConstructor EDITED:")
            print(f"  Text: {latest.text!r}")
            print_buttons(latest)
            constructor_msg = latest

        # Step 3: Click "Имя"
        print("\n--- Step 3: Click 'Имя' ---")
        updated = await click_and_wait(client, entity, constructor_msg, "Имя")
        if updated:
            print(f"After click: {updated.text!r}")
            print_buttons(updated)
            constructor_msg = updated

        # Step 4: Send name
        print("\n--- Step 4: Sending 'Андрей' ---")
        await client.send_message(entity, "Андрей")
        await asyncio.sleep(5)

        latest = await client.get_messages(entity, ids=constructor_msg.id)
        if latest:
            print(f"Constructor: {latest.text!r}")
            print_buttons(latest)
            constructor_msg = latest

        # Step 5: Click "Отчество"
        print("\n--- Step 5: Click 'Отчество' ---")
        updated = await click_and_wait(client, entity, constructor_msg, "Отчество")
        if updated:
            print(f"After click: {updated.text!r}")
            constructor_msg = updated

        # Step 6: Send patronymic
        print("\n--- Step 6: Sending 'Георгиевич' ---")
        await client.send_message(entity, "Георгиевич")
        await asyncio.sleep(5)

        latest = await client.get_messages(entity, ids=constructor_msg.id)
        if latest:
            print(f"Constructor: {latest.text!r}")
            print_buttons(latest)
            constructor_msg = latest

        # Step 7: Click "Искать"
        print("\n--- Step 7: Click 'Искать' ---")
        after_id = (await client.get_messages(entity, limit=1))[0].id
        clicked = await click_inline_button(constructor_msg, "Искать")
        print(f"Clicked: {clicked}")

        # Wait for results
        print("\nWaiting for search results (60s)...")
        start = time.time()
        seen_ids = set()
        while time.time() - start < 60:
            messages = await client.get_messages(entity, limit=10)
            for m in reversed(messages):
                if m.id <= after_id or m.id in seen_ids or m.out:
                    continue
                seen_ids.add(m.id)
                print(f"\n=== Result #{m.id} at {time.time()-start:.1f}s ===")
                print(f"Text: {(m.text or '')[:500]}")
                print_buttons(m)

            # Check constructor edit
            ce = await client.get_messages(entity, ids=constructor_msg.id)
            if ce and ce.text != constructor_msg.text:
                print(f"\nConstructor edited: {ce.text!r}")
                constructor_msg = ce

            await asyncio.sleep(2)

        print(f"\nTotal result messages: {len(seen_ids)}")


if __name__ == "__main__":
    asyncio.run(main())
