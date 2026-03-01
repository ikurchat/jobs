"""Formulation memory — store and retrieve approved report formulations.

Uses Baserow table `formulation_memory` for persistent storage.
Matching is keyword-based (overlap >= threshold of significant words).

CLI usage:
    python -m services.formulation_memory list
    python -m services.formulation_memory search --text "мониторинг событий ИБ"
    python -m services.formulation_memory save --pattern "мониторинг ИБ-событий" --done-text "Выполнено. Обработано {N_events} событий." --variables '["N_events"]'
    python -m services.formulation_memory get_all_as_dict
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from config.settings import get_table_id, load_config, output_error, output_json
from services.baserow import create_row, list_all_rows, update_row


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def search_formulation(
    text: str,
    config: dict | None = None,
    threshold: float | None = None,
) -> dict | None:
    """Find best matching formulation for a given text.

    Returns Baserow row dict or None if no match above threshold.
    """
    cfg = config or load_config()
    thresh = threshold or cfg.get("formulation_memory", {}).get("match_threshold", 0.6)
    min_word_len = cfg.get("formulation_memory", {}).get("min_word_length", 3)

    table_id = get_table_id(cfg, "formulation_memory")
    all_rows = list_all_rows(table_id)

    text_words = _significant_words(text, min_word_len)
    if not text_words:
        return None

    best_row = None
    best_score = 0.0

    for row in all_rows:
        pattern = row.get("task_pattern", "")
        pattern_words = _significant_words(pattern, min_word_len)
        if not pattern_words:
            continue

        overlap = text_words & pattern_words
        score = len(overlap) / min(len(text_words), len(pattern_words))
        if score > best_score and score >= thresh:
            best_score = score
            best_row = row

    return best_row


def save_formulation(
    task_pattern: str,
    status_done_text: str = "",
    status_in_progress_text: str = "",
    variables: list[str] | None = None,
    config: dict | None = None,
) -> dict:
    """Save or update a formulation in Baserow.

    If a matching pattern already exists (overlap >= 80%), updates it.
    Otherwise creates a new row.
    """
    cfg = config or load_config()
    table_id = get_table_id(cfg, "formulation_memory")
    min_word_len = cfg.get("formulation_memory", {}).get("min_word_length", 3)

    # Check for existing match (stricter threshold for dedup)
    existing = _find_existing(task_pattern, table_id, min_word_len, threshold=0.8)

    data = {
        "task_pattern": task_pattern,
        "status_done_text": status_done_text,
        "status_in_progress_text": status_in_progress_text,
        "variables": json.dumps(variables or [], ensure_ascii=False),
        "last_used_date": str(date.today()),
    }

    if existing:
        # Update existing row, increment use_count
        use_count = int(existing.get("use_count", 0) or 0)
        data["use_count"] = use_count + 1
        return update_row(table_id, existing["id"], data)
    else:
        data["use_count"] = 1
        return create_row(table_id, data)


def get_all_as_dict(config: dict | None = None) -> dict[str, str]:
    """Load all formulations as {pattern: done_text} dict for report_builder."""
    cfg = config or load_config()
    table_id = get_table_id(cfg, "formulation_memory")
    rows = list_all_rows(table_id)

    result = {}
    for row in rows:
        pattern = row.get("task_pattern", "")
        done_text = row.get("status_done_text", "")
        if pattern and done_text:
            result[pattern] = done_text
    return result


def bulk_save_approved(
    approved_items: list[dict],
    config: dict | None = None,
) -> int:
    """Save formulations from approved report items.

    Each item should have: description, completion_note (the approved text).
    Returns count of saved formulations.
    """
    cfg = config or load_config()
    saved = 0

    for item in approved_items:
        desc = item.get("description", "")
        mark = item.get("completion_note", "") or item.get("mark_text", "")
        if not desc or not mark:
            continue

        # Only save meaningful marks (not placeholders)
        if mark.startswith("[") and mark.endswith("]"):
            continue

        # Determine status-specific text
        done_text = ""
        in_progress_text = ""
        if mark.startswith("Выполнено"):
            done_text = mark
        elif mark.startswith("В работе"):
            in_progress_text = mark
        else:
            done_text = mark  # default to done

        save_formulation(
            task_pattern=desc,
            status_done_text=done_text,
            status_in_progress_text=in_progress_text,
            config=cfg,
        )
        saved += 1

    return saved


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _significant_words(text: str, min_len: int = 3) -> set[str]:
    """Extract significant words (longer than min_len)."""
    return {w.lower() for w in text.split() if len(w) > min_len}


def _find_existing(
    pattern: str,
    table_id: int,
    min_word_len: int,
    threshold: float = 0.8,
) -> dict | None:
    """Find existing row with high overlap to avoid duplicates."""
    all_rows = list_all_rows(table_id)
    text_words = _significant_words(pattern, min_word_len)
    if not text_words:
        return None

    for row in all_rows:
        row_pattern = row.get("task_pattern", "")
        row_words = _significant_words(row_pattern, min_word_len)
        if not row_words:
            continue
        overlap = text_words & row_words
        score = len(overlap) / min(len(text_words), len(row_words))
        if score >= threshold:
            return row

    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Formulation memory for weekly-ops")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List all formulations")

    p_search = sub.add_parser("search", help="Search formulation by text")
    p_search.add_argument("--text", required=True)

    p_save = sub.add_parser("save", help="Save formulation")
    p_save.add_argument("--pattern", required=True)
    p_save.add_argument("--done-text", default="")
    p_save.add_argument("--in-progress-text", default="")
    p_save.add_argument("--variables", default="[]", help="JSON array of variable names")

    sub.add_parser("get_all_as_dict", help="Get all as {pattern: done_text} dict")

    args = parser.parse_args()
    config = load_config()

    try:
        if args.command == "list":
            table_id = get_table_id(config, "formulation_memory")
            rows = list_all_rows(table_id)
            output_json(rows)

        elif args.command == "search":
            result = search_formulation(args.text, config)
            if result:
                output_json(result)
            else:
                output_json({"match": None, "text": args.text})

        elif args.command == "save":
            variables = json.loads(args.variables)
            result = save_formulation(
                args.pattern, args.done_text, args.in_progress_text, variables, config
            )
            output_json(result)

        elif args.command == "get_all_as_dict":
            result = get_all_as_dict(config)
            output_json(result)

    except (RuntimeError, ValueError, json.JSONDecodeError) as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
