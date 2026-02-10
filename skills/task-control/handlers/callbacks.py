"""Confirmation and update processors — parse owner's responses.

Handles: "ок", "да", "①② в югайл до пятницы, ③ Петрову", etc.
"""

from __future__ import annotations

import re
from typing import Any

# Circled digit → number mapping
CIRCLED_TO_NUM: dict[str, int] = {
    "①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5,
    "⑥": 6, "⑦": 7, "⑧": 8, "⑨": 9, "⑩": 10,
    "⑪": 11, "⑫": 12, "⑬": 13, "⑭": 14, "⑮": 15,
}

# Confirmation keywords
CONFIRM_KEYWORDS = {
    "ок", "ok", "да", "yes", "подтверждаю", "согласен",
    "утверждаю", "верно", "так", "давай", "го",
    "поставил", "записывай", "фиксируй",
}

REJECT_KEYWORDS = {
    "нет", "no", "отмена", "не надо", "отменяй", "стоп",
}

# Delivery method aliases
DELIVERY_ALIASES: dict[str, str] = {
    "югайл": "yougile",
    "yougile": "yougile",
    "email": "email",
    "почта": "email",
    "устно": "verbal",
    "словесно": "verbal",
    "лично": "verbal",
    "тг": "messenger",
    "телеграм": "messenger",
    "мессенджер": "messenger",
    "план": "plan",
}


def parse_confirmation(text: str) -> dict:
    """Parse simple confirmation/rejection.

    Returns {action: "approve" | "reject" | "edit", raw: str}.
    """
    lower = text.strip().lower()

    if lower in CONFIRM_KEYWORDS:
        return {"action": "approve", "raw": text}

    if lower in REJECT_KEYWORDS:
        return {"action": "reject", "raw": text}

    # If contains edits, mark as edit
    return {"action": "edit", "raw": text}


def parse_batch_response(text: str) -> list[dict]:
    """Parse batch response like '①② в югайл до пятницы, ③ Петрову устно до конца смены'.

    Returns list of {numbers: [int], delivery_method, assignee_hint, deadline_hint}.
    """
    result = []

    # Split by comma or semicolon
    parts = re.split(r'[,;]\s*', text.strip())

    for part in parts:
        part = part.strip()
        if not part:
            continue

        entry: dict[str, Any] = {"numbers": [], "edits": {}}

        # Extract circled numbers
        for char in part:
            if char in CIRCLED_TO_NUM:
                entry["numbers"].append(CIRCLED_TO_NUM[char])

        # Also try regular digit references like "1, 2" or "#1 #2"
        if not entry["numbers"]:
            digit_matches = re.findall(r'(?:^|\s|#)(\d{1,2})(?:\s|$|[—\-:])', part)
            entry["numbers"] = [int(d) for d in digit_matches if 1 <= int(d) <= 20]

        if not entry["numbers"]:
            # Might be a general instruction, skip
            continue

        # Extract delivery method
        lower_part = part.lower()
        for alias, method in DELIVERY_ALIASES.items():
            if alias in lower_part:
                entry["edits"]["delivery_method"] = method
                break

        # Extract deadline hint (до + text)
        deadline_match = re.search(r'до\s+(.+?)(?:\s*[,;]|$)', lower_part)
        if deadline_match:
            entry["edits"]["deadline_hint"] = deadline_match.group(1).strip()

        # Extract assignee hint (capitalized name not matching keywords)
        # Look for Russian names (Capitalized word)
        name_matches = re.findall(r'([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)*)', part)
        for name in name_matches:
            name_lower = name.lower()
            # Skip if it's a delivery method or common word
            if name_lower in DELIVERY_ALIASES:
                continue
            if name_lower in ("до", "через", "что", "все", "всем"):
                continue
            entry["edits"]["assignee_hint"] = name
            break

        result.append(entry)

    return result


def parse_status_update(text: str) -> dict:
    """Parse natural language status update.

    Examples:
        "Кулиш сдал справку по PT" → {assignee_hint: "Кулиш", action: "done", task_hint: "справка по PT"}
        "Меликян просит ещё 2 дня" → {assignee_hint: "Меликян", action: "deadline_move", detail: "2 дня"}
        "Снимаю задачу по SOAR" → {action: "cancel", task_hint: "SOAR"}
    """
    lower = text.strip().lower()

    result: dict[str, Any] = {"raw": text}

    # Extract name (first capitalized Russian word)
    name_match = re.search(r'([А-ЯЁ][а-яё]+)', text)
    if name_match:
        result["assignee_hint"] = name_match.group(1)

    # Detect action
    if any(w in lower for w in ["сдал", "выполнил", "готово", "сделал", "закончил", "принёс"]):
        result["action"] = "done"
    elif any(w in lower for w in ["просит ещё", "просит еще", "перенос", "сдвиг"]):
        result["action"] = "deadline_move"
        # Try to extract duration
        dur_match = re.search(r'(\d+)\s*(дн|день|дней|часов|час)', lower)
        if dur_match:
            result["detail"] = dur_match.group(0)
    elif any(w in lower for w in ["снимаю", "отмен", "убираю", "не нужно"]):
        result["action"] = "cancel"
    elif any(w in lower for w in ["начал", "приступил", "взялся", "работает"]):
        result["action"] = "in_progress"
    elif any(w in lower for w in ["поставил", "передал", "назначил"]):
        result["action"] = "assigned"
    else:
        result["action"] = "comment"

    # Extract task hint (after action word, quoted text, or everything after the name)
    # Look for quoted text
    quote_match = re.search(r'[«"](.*?)[»"]', text)
    if quote_match:
        result["task_hint"] = quote_match.group(1)
    else:
        # Take text after "по" or after the name
        po_match = re.search(r'(?:справку|задачу|работу|по)\s+(.+?)(?:\s*[.,]|$)', text)
        if po_match:
            result["task_hint"] = po_match.group(1).strip()

    return result
