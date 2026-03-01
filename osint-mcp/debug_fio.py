"""Debug: send FIO to Sherlock and log everything that comes back."""
import asyncio
import json
import time

from osint_utils import get_telethon_client, wait_for_response
from osint_resolver import resolve_sherlock


async def main():
    client = get_telethon_client()
    async with client:
        result = await resolve_sherlock(client)
        print(f"Resolver: {json.dumps(result, ensure_ascii=False)}")
        if not result.get("valid"):
            print("Bot not resolved!")
            return

        entity = await client.get_entity(result["username"])

        # Get last message ID
        last_msgs = await client.get_messages(entity, limit=1)
        after_id = last_msgs[0].id if last_msgs else 0
        print(f"Last message ID: {after_id}")

        # Send FIO
        fio = "Ткаченко Андрей Георгиевич"
        print(f"\nSending FIO: {fio}")
        await client.send_message(entity, fio)

        # Wait and collect ALL responses for 45 seconds
        print("\nWaiting for responses (45s)...\n")
        start = time.time()
        seen_ids = set()

        while time.time() - start < 45:
            messages = await client.get_messages(entity, limit=10)
            for msg in reversed(messages):
                if msg.id <= after_id or msg.id in seen_ids:
                    continue
                if msg.out:  # Skip our own messages
                    continue
                seen_ids.add(msg.id)

                elapsed = time.time() - start
                print(f"=== Message #{msg.id} at {elapsed:.1f}s ===")
                print(f"Text: {msg.text!r}")
                print(f"Edit date: {msg.edit_date}")

                # Check for inline buttons
                if msg.reply_markup:
                    markup_type = type(msg.reply_markup).__name__
                    print(f"Markup type: {markup_type}")
                    if hasattr(msg.reply_markup, "rows"):
                        for ri, row in enumerate(msg.reply_markup.rows):
                            for bi, btn in enumerate(row.buttons):
                                btn_type = type(btn).__name__
                                btn_text = getattr(btn, "text", "")
                                btn_data = getattr(btn, "data", None)
                                btn_url = getattr(btn, "url", None)
                                print(f"  Button [{ri}][{bi}]: type={btn_type} text={btn_text!r} data={btn_data!r} url={btn_url!r}")
                    elif hasattr(msg.reply_markup, "rows") is False:
                        # ReplyKeyboardMarkup
                        if hasattr(msg.reply_markup, "rows"):
                            for ri, row in enumerate(msg.reply_markup.rows):
                                for bi, btn in enumerate(row.buttons):
                                    print(f"  Keyboard [{ri}][{bi}]: {btn.text!r}")

                # Check for media
                if msg.media:
                    print(f"Media: {type(msg.media).__name__}")

                print()

            await asyncio.sleep(2)

        print(f"\nTotal messages received: {len(seen_ids)}")


if __name__ == "__main__":
    asyncio.run(main())
