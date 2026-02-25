"""
Models — модели данных для внешних пользователей и задач.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
import json

# Valid actions for trusted users
TRUSTED_ACTIONS = ("search", "browser", "schedule", "tasks", "documents")


def _ensure_aware(dt: datetime) -> datetime:
    """Make naive datetime timezone-aware using local timezone."""
    if dt.tzinfo is None:
        return dt.astimezone()
    return dt


@dataclass
class ExternalUser:
    """Внешний пользователь Telegram."""

    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    notes: str = ""
    first_contact: datetime = field(default_factory=datetime.now)
    last_contact: datetime = field(default_factory=datetime.now)
    warnings_count: int = 0
    is_banned: bool = False
    is_whitelisted: bool = False
    role: Literal["external", "trusted"] = "external"
    allowed_actions: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        """Отображаемое имя пользователя."""
        if self.first_name:
            parts = [self.first_name]
            if self.last_name:
                parts.append(self.last_name)
            return " ".join(parts)
        if self.username:
            return f"@{self.username}"
        return str(self.telegram_id)

    @property
    def mention(self) -> str:
        """Упоминание для отправки сообщений."""
        if self.username:
            return f"@{self.username}"
        return self.display_name


@dataclass
class Task:
    """Универсальная единица работы: поручение, согласование, проверка, напоминание."""

    id: str
    title: str
    status: Literal["pending", "in_progress", "done", "cancelled"] = "pending"

    # Кто
    created_by: int | None = None       # telegram_id создателя
    assignee_id: int | None = None      # telegram_id исполнителя (None = системная)

    # Когда
    deadline: datetime | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Что (гибкий payload)
    kind: str = "task"                  # task, meeting, question, check, reminder, scheduled, ...
    context: dict = field(default_factory=dict)  # Входные данные
    result: dict | None = None          # Результат

    # Расписание (для kind="scheduled")
    schedule_at: datetime | None = None      # Следующее время выполнения
    schedule_repeat: int | None = None       # Интервал повтора (секунды), None = одноразово

    # Persistent task session
    next_step: str | None = None             # Текущий шаг для heartbeat
    session_id: str | None = None            # Claude SDK session ID для persistent сессии

    @property
    def is_overdue(self) -> bool:
        """Просрочена ли задача."""
        if self.deadline and self.status not in ("done", "cancelled"):
            now = datetime.now(tz=self.deadline.tzinfo) if self.deadline.tzinfo else datetime.now()
            return now > self.deadline
        return False

    @property
    def is_scheduled(self) -> bool:
        """Является ли задача запланированной."""
        return self.kind == "scheduled" and self.schedule_at is not None

    @staticmethod
    def from_row(row: dict) -> "Task":
        """Создаёт из строки БД."""
        return Task(
            id=row["id"],
            title=row["title"],
            status=row["status"],
            created_by=row["created_by"],
            assignee_id=row["assignee_id"],
            deadline=_ensure_aware(datetime.fromisoformat(row["deadline"])) if row["deadline"] else None,
            created_at=_ensure_aware(datetime.fromisoformat(row["created_at"])) if row["created_at"] else datetime.now().astimezone(),
            updated_at=_ensure_aware(datetime.fromisoformat(row["updated_at"])) if row["updated_at"] else datetime.now().astimezone(),
            kind=row["kind"] or "task",
            context=json.loads(row["context"]) if row["context"] else {},
            result=json.loads(row["result"]) if row["result"] else None,
            schedule_at=_ensure_aware(datetime.fromisoformat(row["schedule_at"])) if row.get("schedule_at") else None,
            schedule_repeat=row.get("schedule_repeat"),
            next_step=row.get("next_step"),
            session_id=row.get("session_id"),
        )
