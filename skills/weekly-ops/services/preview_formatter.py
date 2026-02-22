"""Format plan/report items into Telegram preview blocks.

CLI usage:
    python -m services.preview_formatter plan --data plan.json
    python -m services.preview_formatter report --data report.json
    python -m services.preview_formatter block --data items.json --block-num 1 --block-size 5
"""

from __future__ import annotations

import argparse
import json
import math

from config.settings import load_config, output_error, output_json


CIRCLED_DIGITS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"]


# ---------------------------------------------------------------------------
# Preview formatting
# ---------------------------------------------------------------------------

def format_plan_blocks(
    items: list[dict],
    period_label: str = "",
    block_size: int = 5,
) -> list[str]:
    """Format plan items into Telegram-ready text blocks."""
    blocks = _split_into_blocks(items, block_size)
    total = len(blocks)
    result = []

    for i, block in enumerate(blocks, 1):
        header = f"📋 {period_label} | Блок {i}/{total}:\n" if period_label else f"📋 Блок {i}/{total}:\n"
        lines = []
        for item in block:
            idx = item.get("item_number", 0)
            digit = CIRCLED_DIGITS[idx - 1] if 0 < idx <= len(CIRCLED_DIGITS) else f"({idx})"
            desc = item.get("description", "")
            deadline = item.get("deadline", "")
            responsible = item.get("responsible", "")

            line = f"{digit} {desc}"
            if deadline:
                line += f" | {deadline}"
            if responsible:
                line += f" | {responsible}"
            lines.append(line)

        body = "\n".join(lines)
        footer = "\n\n✅ Подтвердить | ✏️ Правки | ➕ Добавить"
        result.append(header + "\n" + body + footer)

    return result


def format_report_blocks(
    items: list[dict],
    period_label: str = "",
    block_size: int = 5,
) -> list[str]:
    """Format report items (with marks) into Telegram-ready text blocks."""
    blocks = _split_into_blocks(items, block_size)
    total = len(blocks)
    result = []

    for i, block in enumerate(blocks, 1):
        header = f"📊 {period_label} | Блок {i}/{total}:\n" if period_label else f"📊 Блок {i}/{total}:\n"
        lines = []
        for item in block:
            idx = item.get("item_number", 0)
            digit = CIRCLED_DIGITS[idx - 1] if 0 < idx <= len(CIRCLED_DIGITS) else f"({idx})"
            desc = item.get("description", "")
            mark = item.get("completion_note", "") or item.get("mark_text", "")

            lines.append(f"{digit} {desc}")
            if mark:
                lines.append(f"   → {mark}")

        body = "\n".join(lines)
        footer = "\n\n✅ Подтвердить | ✏️ Правки (например: ② 80%, акт подписан)"
        result.append(header + "\n" + body + footer)

    return result


def format_single_block(
    items: list[dict],
    block_num: int,
    block_size: int = 5,
    doc_type: str = "plan",
    period_label: str = "",
) -> str | None:
    """Format a specific block by number (1-based)."""
    blocks = _split_into_blocks(items, block_size)
    if block_num < 1 or block_num > len(blocks):
        return None

    block = blocks[block_num - 1]
    if doc_type == "report":
        return format_report_blocks(block, period_label, block_size=len(block))[0] if block else None
    else:
        return format_plan_blocks(block, period_label, block_size=len(block))[0] if block else None


def get_blocks_total(items: list[dict], block_size: int = 5) -> int:
    """Return total number of blocks."""
    return math.ceil(len(items) / block_size) if items else 0


# ---------------------------------------------------------------------------
# Parsing owner responses
# ---------------------------------------------------------------------------

def parse_owner_response(text: str, block_items: list[dict]) -> dict:
    """Parse owner's response to a preview block.

    Returns:
        {
            "action": "approve" | "edit" | "add" | "remove" | "approve_all",
            "edits": {item_number: new_text, ...},
            "additions": [{description, deadline, responsible}, ...],
            "removals": [item_number, ...],
        }
    """
    text = text.strip().lower()

    # "ок", "да", "подтвердить" → approve current block
    if text in ("ок", "ok", "да", "подтвердить", "подтверждаю", "норм"):
        return {"action": "approve", "edits": {}, "additions": [], "removals": []}

    # "всё ок", "всё хорошо", "all ok" → approve all remaining blocks
    if text in ("всё ок", "все ок", "всё хорошо", "all ok", "всё норм"):
        return {"action": "approve_all", "edits": {}, "additions": [], "removals": []}

    result = {"action": "edit", "edits": {}, "additions": [], "removals": []}

    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # "⑤ убрать" or "5 убрать" → remove
        for digit_idx, digit in enumerate(CIRCLED_DIGITS, 1):
            if line.startswith(digit) or line.startswith(f"{digit_idx} "):
                rest = line.lstrip(digit).lstrip(f"{digit_idx}").strip()
                if rest.startswith("убрать") or rest.startswith("удалить") or rest.startswith("убери"):
                    result["removals"].append(digit_idx)
                else:
                    result["edits"][digit_idx] = rest
                break
        else:
            # "② сроки до пятницы" pattern
            import re
            m = re.match(r'[①②③④⑤⑥⑦⑧⑨⑩]|(\d+)\s+', line)
            if m:
                num_str = m.group(1)
                if num_str:
                    num = int(num_str)
                    rest = line[m.end():].strip()
                    if "убрать" in rest or "удалить" in rest:
                        result["removals"].append(num)
                    else:
                        result["edits"][num] = rest

            # "добавь: ..." → add
            if line.startswith("добавь") or line.startswith("добавить"):
                parts = line.split(":", 1)
                if len(parts) > 1:
                    add_text = parts[1].strip()
                    # Parse "Описание | срок | ответственный"
                    segments = [s.strip() for s in add_text.split("|")]
                    addition = {"description": segments[0]}
                    if len(segments) > 1:
                        addition["deadline"] = segments[1]
                    if len(segments) > 2:
                        addition["responsible"] = segments[2]
                    result["additions"].append(addition)

    return result


def apply_edits(items: list[dict], parsed: dict) -> list[dict]:
    """Apply parsed edits to items list."""
    # Remove items
    removals = set(parsed.get("removals", []))
    items = [it for it in items if it.get("item_number") not in removals]

    # Apply text edits
    for num, edit_text in parsed.get("edits", {}).items():
        for it in items:
            if it.get("item_number") == num:
                # Detect what field is being edited
                if "сроки" in edit_text.lower() or "до " in edit_text.lower():
                    it["deadline"] = edit_text.replace("сроки ", "").strip()
                elif edit_text.endswith("%") or edit_text.startswith("в работе"):
                    it["completion_note"] = edit_text
                else:
                    # Default: update description or completion_note depending on context
                    if it.get("completion_note") is not None:
                        it["completion_note"] = edit_text
                    else:
                        it["description"] = edit_text

    # Add new items
    additions = parsed.get("additions", [])
    next_num = max((it.get("item_number", 0) for it in items), default=0) + 1
    for add in additions:
        items.append({
            "item_number": next_num,
            "description": add.get("description", ""),
            "deadline": add.get("deadline", ""),
            "responsible": add.get("responsible", ""),
            "completion_note": "",
            "is_unplanned": False,
        })
        next_num += 1

    # Renumber
    for i, it in enumerate(items, 1):
        it["item_number"] = i

    return items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_into_blocks(items: list[dict], block_size: int) -> list[list[dict]]:
    """Split items into blocks of given size."""
    return [items[i:i + block_size] for i in range(0, len(items), block_size)]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Preview formatter for weekly-ops")
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="Format plan preview")
    p_plan.add_argument("--data", required=True, help="Plan items JSON")
    p_plan.add_argument("--period", default="", help="Period label")

    p_report = sub.add_parser("report", help="Format report preview")
    p_report.add_argument("--data", required=True, help="Report items JSON")
    p_report.add_argument("--period", default="", help="Period label")

    p_block = sub.add_parser("block", help="Format single block")
    p_block.add_argument("--data", required=True)
    p_block.add_argument("--block-num", type=int, required=True)
    p_block.add_argument("--block-size", type=int, default=5)
    p_block.add_argument("--type", default="plan", choices=["plan", "report"])
    p_block.add_argument("--period", default="")

    args = parser.parse_args()
    config = load_config()
    block_size = config.get("preview", {}).get("block_size", 5)

    try:
        with open(args.data, "r", encoding="utf-8") as f:
            items = json.load(f)

        if args.command == "plan":
            blocks = format_plan_blocks(items, args.period, block_size)
            output_json({"blocks": blocks, "total": len(blocks)})

        elif args.command == "report":
            blocks = format_report_blocks(items, args.period, block_size)
            output_json({"blocks": blocks, "total": len(blocks)})

        elif args.command == "block":
            text = format_single_block(
                items, args.block_num, args.block_size, args.type, args.period
            )
            output_json({"block": text, "block_num": args.block_num})

    except (RuntimeError, ValueError, FileNotFoundError) as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
