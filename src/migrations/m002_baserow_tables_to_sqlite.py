"""Создание таблиц для данных, ранее хранившихся в Baserow."""

from pathlib import Path

import aiosqlite


async def apply(data_dir: Path) -> None:
    db_path = data_dir / "db.sqlite"
    db = await aiosqlite.connect(str(db_path))
    try:
        await db.execute("PRAGMA journal_mode=WAL")

        # ---- employees ----
        await db.execute("""
            CREATE TABLE IF NOT EXISTS br_employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fio TEXT NOT NULL,
                position TEXT DEFAULT '',
                schedule_type TEXT DEFAULT '',
                zone TEXT DEFAULT '',
                strengths TEXT,
                telegram TEXT DEFAULT '',
                phone_internal TEXT DEFAULT '',
                email TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ---- tasks ----
        await db.execute("""
            CREATE TABLE IF NOT EXISTS br_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                source_date TEXT,
                source_text TEXT,
                task_type TEXT DEFAULT '',
                control_loop TEXT DEFAULT '',
                description TEXT DEFAULT '',
                owner_action TEXT DEFAULT '',
                priority TEXT DEFAULT 'normal',
                status TEXT DEFAULT 'draft',
                delivery_method TEXT DEFAULT '',
                assigned_date TEXT,
                deadline TEXT,
                completed_date TEXT,
                result TEXT,
                delay_reason TEXT,
                is_unplanned INTEGER,
                boss_deadline TEXT,
                regulatory_ref TEXT,
                notes TEXT,
                assignee_id INTEGER,
                assigned_shift_id INTEGER,
                handed_to_id INTEGER,
                parent_task_id INTEGER,
                plan_item_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_br_tasks_status ON br_tasks(status)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_br_tasks_assignee ON br_tasks(assignee_id)"
        )

        # ---- shift_schedule ----
        await db.execute("""
            CREATE TABLE IF NOT EXISTS br_shift_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                shift_type TEXT NOT NULL,
                shift_start TEXT DEFAULT '',
                shift_end TEXT DEFAULT '',
                month TEXT DEFAULT '',
                employee_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_br_shifts_date ON br_shift_schedule(date)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_br_shifts_month ON br_shift_schedule(month)"
        )

        # ---- task_log ----
        await db.execute("""
            CREATE TABLE IF NOT EXISTS br_task_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                event_type TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                comment TEXT,
                task_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ---- plan_items ----
        await db.execute("""
            CREATE TABLE IF NOT EXISTS br_plan_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_number INTEGER,
                description TEXT NOT NULL,
                deadline TEXT,
                responsible_id INTEGER,
                responsible_name TEXT DEFAULT '',
                period_type TEXT DEFAULT 'weekly',
                period_start TEXT,
                period_end TEXT,
                status TEXT DEFAULT 'pending',
                completion_note TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ---- regulatory_tracks ----
        await db.execute("""
            CREATE TABLE IF NOT EXISTS br_regulatory_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                regulation TEXT NOT NULL,
                requirement TEXT DEFAULT '',
                deadline TEXT,
                next_deadline TEXT,
                status TEXT DEFAULT 'not_started',
                responsible_id INTEGER,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ---- sender_profiles ----
        await db.execute("""
            CREATE TABLE IF NOT EXISTS br_sender_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT DEFAULT '',
                sender_email TEXT DEFAULT '',
                sender_name TEXT DEFAULT '',
                sender_domain TEXT DEFAULT '',
                default_priority TEXT,
                default_category TEXT,
                default_action TEXT,
                is_vip INTEGER DEFAULT 0,
                total_emails INTEGER DEFAULT 0,
                total_feedbacks INTEGER DEFAULT 0,
                avg_confidence REAL,
                avg_effort_minutes REAL,
                notes TEXT,
                active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ---- formulation_memory ----
        await db.execute("""
            CREATE TABLE IF NOT EXISTS br_formulation_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_pattern TEXT NOT NULL,
                status_done_text TEXT DEFAULT '',
                status_in_progress_text TEXT DEFAULT '',
                variables TEXT DEFAULT '[]',
                last_used_date TEXT,
                use_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.commit()
    finally:
        await db.close()
