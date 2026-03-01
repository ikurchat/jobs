"""Debug: send FIO+date to Sherlock and log response."""
import asyncio
import json
import time

from osint_utils import get_telethon_client
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

        print("Waiting 45s...")
        start = time.time()
        seen = set()
        while time.time() - start < 45:
            msgs = await client.get_messages(entity, limit=10)
            for m in reversed(msgs):
                if m.id <= after_id or m.id in seen or m.out:
                    continue
                seen.add(m.id)
                t = time.time() - start
                print(f"\n=== #{m.id} at {t:.1f}s ===")
                print(f"Text: {(m.text or '')[:300]}")
                if m.reply_markup and hasattr(m.reply_markup, "rows"):
                    for ri, row in enumerate(m.reply_markup.rows):
                        for bi, btn in enumerate(row.buttons):
                            url = getattr(btn, "url", None)
                            data = getattr(btn, "data", None)
                            print(f"  Btn[{ri}][{bi}]: {btn.text!r} url={url!r} data={data!r}")
            await asyncio.sleep(2)
        print(f"\nTotal: {len(seen)}")

asyncio.run(main())
