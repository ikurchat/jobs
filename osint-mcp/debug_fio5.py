"""Debug: test full FIO+date flow with country auto-click."""
import asyncio
import json
import time

from osint_utils import (
    get_telethon_client,
    wait_for_all_responses,
    wait_for_message_edit,
    click_inline_button,
)
from osint_resolver import resolve_sherlock


async def main():
    client = get_telethon_client()
    async with client:
        result = await resolve_sherlock(client)
        print(f"Bot: {result['username']}")
        entity = await client.get_entity(result["username"])

        last_msgs = await client.get_messages(entity, limit=1)
        after_id = last_msgs[0].id if last_msgs else 0

        # Send FIO+date
        query = "Ткаченко Андрей Георгиевич 10.11.1974"
        print(f"Sending: {query}")
        await client.send_message(entity, query)

        print("Waiting for country menu (30s)...")
        responses = await wait_for_all_responses(
            client, entity, after_id, timeout=30, silence_timeout=10,
        )
        print(f"Got {len(responses)} response(s)")

        # Check for country menu
        country_clicked = False
        for resp in responses:
            print(f"\nMsg #{resp.id}: {(resp.text or '')[:200]}")
            if resp.reply_markup and hasattr(resp.reply_markup, "rows"):
                for ri, row in enumerate(resp.reply_markup.rows):
                    for bi, btn in enumerate(row.buttons):
                        data = getattr(btn, "data", None)
                        print(f"  Btn[{ri}][{bi}]: {btn.text!r} data={data!r}")
                        if data and b"PERSON/" in (data if isinstance(data, bytes) else data.encode()):
                            if not country_clicked:
                                print(f"\n--- Clicking 'Россия' ---")
                                ru_clicked = await click_inline_button(resp, "Россия")
                                if not ru_clicked:
                                    print("Fallback: clicking first button")
                                    await resp.click(0, 0)
                                country_clicked = True

        if not country_clicked:
            print("No country menu found!")
            return

        print("\nWaiting for search results (90s)...")
        latest_id = max(r.id for r in responses)
        start = time.time()
        seen = set()

        # First wait for new messages
        search_responses = await wait_for_all_responses(
            client, entity, latest_id, timeout=90, silence_timeout=15,
        )
        print(f"Got {len(search_responses)} result message(s)")

        for r in search_responses:
            print(f"\n=== #{r.id} at {time.time()-start:.1f}s ===")
            print(f"Text: {(r.text or '')[:500]}")
            if r.reply_markup and hasattr(r.reply_markup, "rows"):
                for ri, row in enumerate(r.reply_markup.rows):
                    for bi, btn in enumerate(row.buttons):
                        url = getattr(btn, "url", None)
                        print(f"  Btn[{ri}][{bi}]: {btn.text!r} url={url!r}")

        if not search_responses:
            # Maybe the country menu message was edited
            print("No new messages, checking edits...")
            for resp in responses:
                edited = await wait_for_message_edit(
                    client, entity, resp.id, timeout=30,
                    original_text=resp.text, original_edit_date=resp.edit_date,
                )
                if edited and edited.text != (resp.text or ""):
                    print(f"Edited msg #{resp.id}: {(edited.text or '')[:500]}")

        print(f"\nDone in {time.time()-start:.1f}s")


asyncio.run(main())
