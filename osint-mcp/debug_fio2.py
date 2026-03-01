"""Debug: click 'Поиск по неполным данным' and see constructor UI."""
import asyncio
import json
import time

from osint_utils import get_telethon_client, wait_for_response, click_inline_button
from osint_resolver import resolve_sherlock


async def main():
    client = get_telethon_client()
    async with client:
        result = await resolve_sherlock(client)
        print(f"Resolver: {json.dumps(result, ensure_ascii=False)}")
        entity = await client.get_entity(result["username"])

        # Get last message
        last_msgs = await client.get_messages(entity, limit=1)
        msg = last_msgs[0]
        after_id = msg.id
        print(f"Last message ID: {after_id}")
        print(f"Last message text (first 100): {(msg.text or '')[:100]}...")

        # Click "Поиск по неполным данным"
        print("\nClicking 'Поиск по неполным данным'...")
        clicked = await click_inline_button(msg, "неполным данным")
        print(f"Clicked: {clicked}")

        if not clicked:
            # Try on a fresh /start
            print("Trying /start first...")
            await client.send_message(entity, "/start")
            await asyncio.sleep(3)
            last_msgs = await client.get_messages(entity, limit=1)
            msg = last_msgs[0]
            after_id = msg.id
            clicked = await click_inline_button(msg, "неполным данным")
            print(f"Clicked after /start: {clicked}")

        # Wait and collect responses
        print("\nWaiting for constructor response (30s)...\n")
        start = time.time()
        seen_ids = set()

        while time.time() - start < 30:
            messages = await client.get_messages(entity, limit=10)
            for m in reversed(messages):
                if m.id <= after_id or m.id in seen_ids or m.out:
                    continue
                seen_ids.add(m.id)

                elapsed = time.time() - start
                print(f"=== Message #{m.id} at {elapsed:.1f}s ===")
                print(f"Text: {m.text!r}")
                print(f"Edit date: {m.edit_date}")

                if m.reply_markup:
                    markup_type = type(m.reply_markup).__name__
                    print(f"Markup type: {markup_type}")
                    if hasattr(m.reply_markup, "rows"):
                        for ri, row in enumerate(m.reply_markup.rows):
                            for bi, btn in enumerate(row.buttons):
                                btn_type = type(btn).__name__
                                btn_text = getattr(btn, "text", "")
                                btn_data = getattr(btn, "data", None)
                                btn_url = getattr(btn, "url", None)
                                print(f"  Button [{ri}][{bi}]: type={btn_type} text={btn_text!r} data={btn_data!r} url={btn_url!r}")
                print()

            # Also check if the original message was edited
            edited = await client.get_messages(entity, ids=msg.id)
            if edited and edited.edit_date and (edited.edit_date != msg.edit_date or edited.text != msg.text):
                print(f"=== EDIT of #{msg.id} ===")
                print(f"New text: {edited.text!r}")
                if edited.reply_markup and hasattr(edited.reply_markup, "rows"):
                    for ri, row in enumerate(edited.reply_markup.rows):
                        for bi, btn in enumerate(row.buttons):
                            btn_text = getattr(btn, "text", "")
                            btn_data = getattr(btn, "data", None)
                            btn_url = getattr(btn, "url", None)
                            print(f"  Button [{ri}][{bi}]: text={btn_text!r} data={btn_data!r} url={btn_url!r}")
                print()
                msg = edited  # Update reference

            await asyncio.sleep(2)

        print(f"\nTotal new messages: {len(seen_ids)}")


if __name__ == "__main__":
    asyncio.run(main())
