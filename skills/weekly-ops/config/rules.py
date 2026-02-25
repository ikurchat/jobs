"""Business rules for weekly-ops: mandatory items, exclusions, deadlines, LL sync."""

from __future__ import annotations

from config.settings import load_config


def get_rules(config: dict | None = None) -> dict:
    """Return merged rules from config.json."""
    cfg = config or load_config()
    return cfg.get("rules", {})


# ---------------------------------------------------------------------------
# Mandatory items — always included in plans
# ---------------------------------------------------------------------------

MANDATORY_ITEMS = [
    {
        "description": "Согласование Порядка мониторинга информационной безопасности (Молотова А.В.)",
        "deadline": "В течение недели",
        "responsible": "Управление ИБ",
    },
    {
        "description": "Мониторинг событий информационной безопасности",
        "deadline": "В течение недели",
        "responsible": "Управление ИБ",
    },
    {
        "description": "Контроль за деятельностью стажёра (Ворожбит)",
        "deadline": "В течение недели",
        "responsible": "Управление ИБ",
    },
]


# ---------------------------------------------------------------------------
# Excluded topics — never include in plans/reports
# ---------------------------------------------------------------------------

EXCLUDE_TOPICS = [
    "цок",
    "центр обеспечения кибербезопасности",
    "доработка бота",
    "настройка скилл",
    "доработка скилл",
    "обновление бота",
    "skills",
    "telegram bot",
    "claude",
    "ai assistant",
]


# ---------------------------------------------------------------------------
# Contractor rules (LL-9): replace FIO with department name
# ---------------------------------------------------------------------------

CONTRACTOR_REPLACEMENTS = {
    # FIO → department/organization
    # Owner fills this as needed; pattern: contractor name → "СИТ" or org name
}

CONTRACTOR_DEPARTMENT = "СИТ"


# ---------------------------------------------------------------------------
# Deadlines
# ---------------------------------------------------------------------------

DEADLINES = {
    "weekly_plan": "friday",
    "weekly_report": "friday",
    "monthly_plan": 20,
    "monthly_report": 20,
    "monthly_weekend_extension": True,
    "monthly_weekend_max_day": 22,
    "monthly_weekend_requires_owner_ok": True,
}


# ---------------------------------------------------------------------------
# Validation rules (Lesson-Learned)
# ---------------------------------------------------------------------------

def validate_plan_item(item: dict) -> list[str]:
    """Validate a single plan item against LL rules. Returns list of issues."""
    issues = []
    desc = item.get("description", "")
    desc_lower = desc.lower()

    # LL-8: No percentages in plans
    if "%" in desc:
        issues.append(f"LL-8: проценты в плане запрещены: «{desc[:60]}»")

    # LL-9: No contractor FIO — only department
    for fio in CONTRACTOR_REPLACEMENTS:
        if fio.lower() in desc_lower:
            issues.append(
                f"LL-9: ФИО подрядчика «{fio}» → замените на «{CONTRACTOR_DEPARTMENT}»"
            )

    # Exclude topics
    for topic in EXCLUDE_TOPICS:
        if topic in desc_lower:
            issues.append(f"Excluded topic «{topic}» found in: «{desc[:60]}»")

    return issues


def validate_report_item(plan_desc: str, additional_descs: list[str]) -> list[str]:
    """LL-3: Check that an additional item doesn't duplicate a planned one."""
    issues = []
    plan_words = set(plan_desc.lower().split())
    plan_significant = {w for w in plan_words if len(w) > 3}

    for add_desc in additional_descs:
        add_words = set(add_desc.lower().split())
        add_significant = {w for w in add_words if len(w) > 3}
        if plan_significant and add_significant:
            overlap = plan_significant & add_significant
            ratio = len(overlap) / min(len(plan_significant), len(add_significant))
            if ratio >= 0.6:
                issues.append(
                    f"LL-3: дополнительный пункт «{add_desc[:50]}» "
                    f"дублирует плановый «{plan_desc[:50]}» (overlap {ratio:.0%})"
                )

    return issues


def is_excluded(text: str) -> bool:
    """Check if text matches any excluded topic (word-root matching)."""
    text_lower = text.lower()
    text_words = set(text_lower.split())
    for topic in EXCLUDE_TOPICS:
        # Direct substring match
        if topic in text_lower:
            return True
        # Word-root match: check if any word in text starts with topic root (≥4 chars)
        topic_words = topic.split()
        for tw in topic_words:
            if len(tw) < 4:
                continue
            root = tw[:min(len(tw), 6)]
            if any(w.startswith(root) for w in text_words):
                # Check all topic words have a root match
                all_match = True
                for tw2 in topic_words:
                    if len(tw2) < 4:
                        continue
                    r2 = tw2[:min(len(tw2), 6)]
                    if not any(w.startswith(r2) for w in text_words):
                        all_match = False
                        break
                if all_match:
                    return True
    return False


def check_mandatory_items(items: list[dict]) -> list[dict]:
    """Return mandatory items that are missing from the list."""
    existing_lower = {item.get("description", "").lower() for item in items}
    missing = []
    for mandatory in MANDATORY_ITEMS:
        # Check by keyword overlap
        m_words = set(mandatory["description"].lower().split())
        m_significant = {w for w in m_words if len(w) > 3}
        found = False
        for existing in existing_lower:
            e_words = set(existing.split())
            e_significant = {w for w in e_words if len(w) > 3}
            if m_significant and e_significant:
                overlap = m_significant & e_significant
                if len(overlap) / len(m_significant) >= 0.5:
                    found = True
                    break
        if not found:
            missing.append(mandatory)
    return missing
