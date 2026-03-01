"""Aggregate weekly plan_items into a monthly report.

CLI usage:
    python -m services.monthly_aggregator aggregate --month 2026-02 --output /dev/shm/weekly-ops/monthly.json
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from calendar import monthrange

from config.settings import load_config, output_error, output_json
from services.data_loader import load_plan_items, _parse_date


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_month(
    month_str: str,
    config: dict | None = None,
) -> dict:
    """Aggregate all weekly plan_items for a month into a single report.

    Args:
        month_str: "YYYY-MM" format
        config: optional config dict

    Returns:
        {
            "items": [merged items],
            "month": "YYYY-MM",
            "period_start": "YYYY-MM-01",
            "period_end": "YYYY-MM-DD",
            "stats": {"total": N, "deduplicated": M, "unplanned": K}
        }
    """
    cfg = config or load_config()
    year, month = map(int, month_str.split("-"))
    _, last_day = monthrange(year, month)
    period_start = date(year, month, 1)
    period_end = date(year, month, last_day)

    # Load ALL plan_items for the entire month
    all_items = load_plan_items(cfg, period_start, period_end)

    # Deduplicate: keep latest version of each item (by description overlap)
    merged = _deduplicate_items(all_items)

    # Separate planned vs unplanned, unplanned at the end
    planned = [it for it in merged if not it.get("is_unplanned", False)]
    unplanned = [it for it in merged if it.get("is_unplanned", False)]
    final = planned + unplanned

    # Renumber
    for i, item in enumerate(final, 1):
        item["item_number"] = i

    return {
        "items": final,
        "month": month_str,
        "period_start": str(period_start),
        "period_end": str(period_end),
        "stats": {
            "total": len(final),
            "deduplicated": len(all_items) - len(merged),
            "unplanned": len(unplanned),
        },
    }


def _deduplicate_items(items: list[dict]) -> list[dict]:
    """Deduplicate items by description overlap, keeping the latest version."""
    seen: dict[str, dict] = {}  # normalized_key → item

    for item in items:
        desc = item.get("description", "")
        key = _normalize_key(desc)
        if not key:
            continue

        # Check if we already have a similar item
        matched_key = None
        for existing_key in seen:
            if _keys_overlap(key, existing_key, threshold=0.6):
                matched_key = existing_key
                break

        if matched_key:
            # Keep the one with more complete data (prefer filled completion_note)
            existing = seen[matched_key]
            new_note = item.get("completion_note", "")
            old_note = existing.get("completion_note", "")
            if new_note and not old_note:
                seen[matched_key] = item
            elif new_note and old_note:
                # Keep the latest (higher row id = newer)
                if (item.get("id", 0) or 0) > (existing.get("id", 0) or 0):
                    seen[matched_key] = item
        else:
            seen[key] = item

    return list(seen.values())


def _normalize_key(text: str) -> str:
    """Create normalized key from description for dedup."""
    words = sorted(w.lower() for w in text.split() if len(w) > 3)
    return " ".join(words)


def _keys_overlap(key1: str, key2: str, threshold: float = 0.6) -> bool:
    """Check if two normalized keys overlap enough."""
    words1 = set(key1.split())
    words2 = set(key2.split())
    if not words1 or not words2:
        return False
    overlap = words1 & words2
    return len(overlap) / min(len(words1), len(words2)) >= threshold


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Monthly aggregator for weekly-ops")
    sub = parser.add_subparsers(dest="command", required=True)

    p_agg = sub.add_parser("aggregate", help="Aggregate weekly items into monthly")
    p_agg.add_argument("--month", required=True, help="YYYY-MM format")
    p_agg.add_argument("--output", help="Output JSON path")

    args = parser.parse_args()
    config = load_config()

    try:
        if args.command == "aggregate":
            result = aggregate_month(args.month, config)

            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                output_json({"path": args.output, "stats": result["stats"]})
            else:
                output_json(result)

    except (RuntimeError, ValueError) as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
