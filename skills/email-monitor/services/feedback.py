"""Система обучения на обратной связи owner'а.

Хранит feedback в локальном SQLite, строит профили отправителей,
повышает confidence при подтверждении паттернов.
Поддерживает коррекции ("ты пропустил важное") и стоп-слова.

CLI: python -m services.feedback record --sender EMAIL --action ACTION [--priority PRI] [--category CAT]
     python -m services.feedback correct --sender EMAIL --priority PRI [--note "описание"]
     python -m services.feedback stop_word --add WORD | --remove WORD | --list
     python -m services.feedback profile --sender EMAIL
     python -m services.feedback history [--sender EMAIL] [--limit N]
     python -m services.feedback stats
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import load_config, output_json, output_error
from models.enums import PatternType

_DB_PATH = Path("/data/email_learning.db")


def _get_db() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sender_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_email TEXT UNIQUE NOT NULL,
            sender_name TEXT DEFAULT '',
            category TEXT DEFAULT '',
            default_priority TEXT DEFAULT '',
            default_action TEXT DEFAULT '',
            confidence REAL DEFAULT 0.5,
            decision_count INTEGER DEFAULT 0,
            correction_count INTEGER DEFAULT 0,
            last_decision_date TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS email_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_email TEXT NOT NULL,
            sender_name TEXT DEFAULT '',
            pattern_type TEXT DEFAULT 'sender',
            pattern_value TEXT DEFAULT '',
            learned_action TEXT DEFAULT '',
            learned_priority TEXT DEFAULT '',
            learned_category TEXT DEFAULT '',
            is_correction INTEGER DEFAULT 0,
            correction_note TEXT DEFAULT '',
            confidence REAL DEFAULT 0.5,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS stop_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE NOT NULL,
            reason TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_feedback_sender
            ON email_feedback(sender_email);
        CREATE INDEX IF NOT EXISTS idx_profiles_email
            ON sender_profiles(sender_email);
    """)
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_feedback(sender_email: str, sender_name: str = "",
                    action: str = "", priority: str = "",
                    category: str = "", pattern_value: str = "") -> dict:
    """Записать обратную связь owner'а."""
    cfg = load_config()["learning"]
    conn = _get_db()
    now = _now()

    # Записываем в лог feedback
    conn.execute(
        """INSERT INTO email_feedback
           (sender_email, sender_name, pattern_type, pattern_value,
            learned_action, learned_priority, learned_category,
            confidence, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (sender_email, sender_name, PatternType.SENDER.value,
         pattern_value or sender_email, action, priority, category,
         0.5, now)
    )

    # Обновляем/создаём профиль отправителя
    existing = conn.execute(
        "SELECT * FROM sender_profiles WHERE sender_email = ?",
        (sender_email,)
    ).fetchone()

    if existing:
        new_count = existing["decision_count"] + 1
        new_confidence = min(1.0, existing["confidence"] + cfg["confidence_increment"])
        updates = {
            "decision_count": new_count,
            "confidence": new_confidence,
            "last_decision_date": now,
            "updated_at": now,
        }
        if action:
            updates["default_action"] = action
        if priority:
            updates["default_priority"] = priority
        if category:
            updates["category"] = category
        if sender_name:
            updates["sender_name"] = sender_name

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE sender_profiles SET {set_clause} WHERE sender_email = ?",
            (*updates.values(), sender_email)
        )
        conn.commit()
        conn.close()
        return {
            "status": "updated",
            "confidence": new_confidence,
            "decision_count": new_count,
        }
    else:
        conn.execute(
            """INSERT INTO sender_profiles
               (sender_email, sender_name, category,
                default_priority, default_action, confidence,
                decision_count, last_decision_date, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sender_email, sender_name, category,
             priority, action, 0.5,
             1, now, now, now)
        )
        conn.commit()
        conn.close()
        return {"status": "created", "confidence": 0.5, "decision_count": 1}


def record_correction(sender_email: str, correct_priority: str,
                      note: str = "") -> dict:
    """Owner говорит 'ты пропустил важное' — коррекция с двойным весом."""
    cfg = load_config()["learning"]
    conn = _get_db()
    now = _now()

    # Записываем коррекцию в лог
    conn.execute(
        """INSERT INTO email_feedback
           (sender_email, pattern_type, learned_priority,
            is_correction, correction_note, confidence, created_at)
           VALUES (?, ?, ?, 1, ?, ?, ?)""",
        (sender_email, PatternType.SENDER.value,
         correct_priority, note, 0.9, now)
    )

    # Обновляем профиль с двойным инкрементом
    existing = conn.execute(
        "SELECT * FROM sender_profiles WHERE sender_email = ?",
        (sender_email,)
    ).fetchone()

    double_increment = cfg["confidence_increment"] * 2

    if existing:
        new_confidence = min(1.0, existing["confidence"] + double_increment)
        new_corrections = existing["correction_count"] + 1
        conn.execute(
            """UPDATE sender_profiles
               SET default_priority = ?, confidence = ?,
                   correction_count = ?, updated_at = ?
               WHERE sender_email = ?""",
            (correct_priority, new_confidence, new_corrections, now, sender_email)
        )
    else:
        conn.execute(
            """INSERT INTO sender_profiles
               (sender_email, default_priority, confidence,
                correction_count, decision_count,
                created_at, updated_at, last_decision_date)
               VALUES (?, ?, ?, 1, 0, ?, ?, ?)""",
            (sender_email, correct_priority, 0.5 + double_increment, now, now, now)
        )

    conn.commit()
    conn.close()
    return {"status": "correction_recorded", "priority": correct_priority, "note": note}


def add_stop_word(word: str, reason: str = "") -> dict:
    """Добавить стоп-слово — письма с ним не показываются."""
    conn = _get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO stop_words (word, reason, created_at) VALUES (?, ?, ?)",
            (word.lower(), reason, _now())
        )
        conn.commit()
        return {"status": "added", "word": word}
    finally:
        conn.close()


def remove_stop_word(word: str) -> dict:
    conn = _get_db()
    conn.execute("DELETE FROM stop_words WHERE word = ?", (word.lower(),))
    conn.commit()
    conn.close()
    return {"status": "removed", "word": word}


def get_stop_words() -> list[str]:
    conn = _get_db()
    rows = conn.execute("SELECT word FROM stop_words").fetchall()
    conn.close()
    return [r["word"] for r in rows]


def get_feedback_history(sender_email: str = "", limit: int = 100) -> list[dict]:
    conn = _get_db()
    if sender_email:
        rows = conn.execute(
            """SELECT * FROM email_feedback
               WHERE sender_email = ?
               ORDER BY created_at DESC LIMIT ?""",
            (sender_email, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM email_feedback ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sender_profile(sender_email: str) -> dict:
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM sender_profiles WHERE sender_email = ?",
        (sender_email,)
    ).fetchone()
    conn.close()

    if not row:
        return {"email": sender_email, "status": "unknown", "total_feedbacks": 0}

    return {
        "email": row["sender_email"],
        "name": row["sender_name"],
        "category": row["category"],
        "default_action": row["default_action"],
        "default_priority": row["default_priority"],
        "confidence": row["confidence"],
        "decision_count": row["decision_count"],
        "correction_count": row["correction_count"],
        "last_decision": row["last_decision_date"],
        "status": "profiled",
    }


def get_all_profiles_for_classifier() -> list[dict]:
    """Возвращает все профили с confidence >= threshold для classifier."""
    cfg = load_config()
    threshold = cfg["classification"]["confidence_threshold"]
    conn = _get_db()
    rows = conn.execute(
        """SELECT sender_email, sender_name, default_priority,
                  default_action, category AS learned_category, confidence
           FROM sender_profiles
           WHERE confidence >= ?""",
        (threshold,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    conn = _get_db()
    total = conn.execute("SELECT COUNT(*) as cnt FROM email_feedback").fetchone()["cnt"]
    senders = conn.execute(
        "SELECT COUNT(DISTINCT sender_email) as cnt FROM sender_profiles"
    ).fetchone()["cnt"]
    corrections = conn.execute(
        "SELECT COUNT(*) as cnt FROM email_feedback WHERE is_correction = 1"
    ).fetchone()["cnt"]
    avg_conf = conn.execute(
        "SELECT AVG(confidence) as avg FROM sender_profiles"
    ).fetchone()["avg"] or 0
    stop_count = conn.execute("SELECT COUNT(*) as cnt FROM stop_words").fetchone()["cnt"]

    action_rows = conn.execute(
        """SELECT default_action, COUNT(*) as cnt
           FROM sender_profiles WHERE default_action != ''
           GROUP BY default_action"""
    ).fetchall()
    action_dist = {r["default_action"]: r["cnt"] for r in action_rows}

    top_rows = conn.execute(
        """SELECT sender_email, sender_name, confidence, decision_count
           FROM sender_profiles ORDER BY confidence DESC LIMIT 5"""
    ).fetchall()

    conn.close()
    return {
        "total_feedbacks": total,
        "unique_senders": senders,
        "corrections": corrections,
        "avg_confidence": round(avg_conf, 2),
        "stop_words_count": stop_count,
        "action_distribution": action_dist,
        "top_confident": [dict(r) for r in top_rows],
    }


def apply_decay():
    """Снижает confidence для профилей без недавних решений."""
    cfg = load_config()["learning"]
    decay_days = cfg.get("confidence_decay_days", 30)
    conn = _get_db()
    conn.execute(
        """UPDATE sender_profiles
           SET confidence = MAX(0.1, confidence * 0.95),
               updated_at = ?
           WHERE last_decision_date < datetime('now', ?)
             AND confidence > 0.1""",
        (_now(), f"-{decay_days} days")
    )
    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Feedback & learning system (SQLite)")
    sub = parser.add_subparsers(dest="command")

    p_rec = sub.add_parser("record")
    p_rec.add_argument("--sender", required=True, help="Email отправителя")
    p_rec.add_argument("--sender-name", default="")
    p_rec.add_argument("--action", default="", help="OwnerAction value")
    p_rec.add_argument("--priority", default="", help="Priority value")
    p_rec.add_argument("--category", default="", help="Category value")

    p_cor = sub.add_parser("correct")
    p_cor.add_argument("--sender", required=True, help="Email отправителя")
    p_cor.add_argument("--priority", required=True, help="Правильный приоритет")
    p_cor.add_argument("--note", default="", help="Описание коррекции")

    p_sw = sub.add_parser("stop_word")
    p_sw.add_argument("--add", default="", help="Добавить стоп-слово")
    p_sw.add_argument("--remove", default="", help="Удалить стоп-слово")
    p_sw.add_argument("--list", action="store_true", help="Показать все")

    p_prof = sub.add_parser("profile")
    p_prof.add_argument("--sender", required=True)

    p_hist = sub.add_parser("history")
    p_hist.add_argument("--sender", default="")
    p_hist.add_argument("--limit", type=int, default=100)

    sub.add_parser("stats")
    sub.add_parser("decay")

    args = parser.parse_args()

    if args.command == "record":
        output_json(record_feedback(
            args.sender, getattr(args, "sender_name", ""),
            args.action, args.priority, getattr(args, "category", "")
        ))
    elif args.command == "correct":
        output_json(record_correction(args.sender, args.priority, args.note))
    elif args.command == "stop_word":
        if args.add:
            output_json(add_stop_word(args.add))
        elif args.remove:
            output_json(remove_stop_word(args.remove))
        else:
            output_json(get_stop_words())
    elif args.command == "profile":
        output_json(get_sender_profile(args.sender))
    elif args.command == "history":
        output_json(get_feedback_history(args.sender, args.limit))
    elif args.command == "stats":
        output_json(get_stats())
    elif args.command == "decay":
        apply_decay()
        output_json({"status": "decay_applied"})
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
