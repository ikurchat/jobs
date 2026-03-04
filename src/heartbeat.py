"""
Heartbeat — периодическая проверка с проактивными уведомлениями.

Каждые N минут агент "просыпается" и решает:
- Есть ли что-то важное для пользователя?
- Есть ли просроченные задачи?
- Если да → пишет в Telegram
- Если нет → молчит (HEARTBEAT_OK)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from src.config import settings
from src.users.prompts import HEARTBEAT_PROMPT

if TYPE_CHECKING:
    from src.telegram.transport import Transport
    from src.triggers.executor import TriggerExecutor
    from src.users.session_manager import SessionManager
    from src.users.models import Task
    from src.users.repository import UsersRepository


# Маркер что всё ок, не нужно писать пользователю
HEARTBEAT_OK_MARKER = "HEARTBEAT_OK"

# Интервал по умолчанию (минуты)
DEFAULT_INTERVAL_MINUTES = 30

MAX_MESSAGE_LENGTH = 4000


class HeartbeatRunner:
    """
    Периодический heartbeat для проактивных уведомлений.

    Использует отдельную сессию (не owner), чтобы не прерывать
    активный диалог. Каждые interval минут:
    1. Проверяет просроченные задачи пользователей
    2. Запрашивает агента через heartbeat session
    3. Если ответ содержит HEARTBEAT_OK — тишина
    """

    def __init__(
        self,
        executor: TriggerExecutor,
        transport: "Transport",
        session_manager: SessionManager,
        interval_minutes: int = DEFAULT_INTERVAL_MINUTES,
    ) -> None:
        self._executor = executor
        self._transport = transport
        self._session_manager = session_manager
        self._interval = interval_minutes * 60  # в секунды
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Запускает heartbeat loop."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Heartbeat started (interval: {self._interval // 60} min)")

    async def stop(self) -> None:
        """Останавливает heartbeat."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Heartbeat stopped")

    async def _loop(self) -> None:
        """Основной цикл."""
        # Первый heartbeat через interval (не сразу)
        await asyncio.sleep(self._interval)

        while self._running:
            try:
                await self._check()
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

            await asyncio.sleep(self._interval)

    async def _check(self) -> None:
        """Выполняет проверку через одноразовую heartbeat session."""
        logger.debug("Heartbeat check started")

        # 1. Проверяем просроченные задачи пользователей
        await self._check_user_tasks()

        # 2. Проверяем task sessions (persistent)
        task_messages = await self._check_task_sessions()

        # 3. Основная heartbeat проверка
        prompt = await self._build_heartbeat_prompt()

        session = self._session_manager.create_heartbeat_session()
        try:
            content = await session.query(prompt)
        finally:
            await session.destroy()
        content = content.strip()

        if HEARTBEAT_OK_MARKER in content:
            logger.debug(f"Heartbeat: silent ({HEARTBEAT_OK_MARKER})")
        else:
            content = content.replace(HEARTBEAT_OK_MARKER, "").strip()
            if content:
                message = f"\U0001f4a1\n{content}"
                if len(message) > MAX_MESSAGE_LENGTH:
                    message = message[:MAX_MESSAGE_LENGTH] + "..."
                await self._transport.send_message(settings.primary_owner_id, message)
                logger.info(f"Heartbeat notification sent: {content[:80]}...")

        # 4. Если task sessions вернули сообщения — отправляем
        if task_messages:
            combined = "\n".join(task_messages)
            await self._transport.send_message(settings.primary_owner_id, f"💎 Задачи:\n{combined}")

    async def _check_task_sessions(self) -> list[str]:
        """Resume task sessions параллельно для проверки состояния."""
        from src.users.repository import get_users_repository

        repo = get_users_repository()
        active = await repo.list_tasks(include_done=False)
        tasks_with_sessions = [t for t in active if t.session_id]

        if not tasks_with_sessions:
            return []

        results = await asyncio.gather(
            *[self._check_single_task_session(t, repo) for t in tasks_with_sessions],
            return_exceptions=True,
        )

        messages: list[str] = []
        for task, result in zip(tasks_with_sessions, results):
            if isinstance(result, Exception):
                logger.error(f"Heartbeat task [{task.id}] error: {result}")
            elif result:
                messages.append(result)
        return messages

    async def _check_single_task_session(self, task: "Task", repo: "UsersRepository") -> str | None:
        """Проверяет одну task session (вызывается параллельно)."""
        session = self._session_manager.get_task_session(task.id, task.session_id)
        if session is None:
            return None

        prompt = (
            f"Heartbeat check задачи [{task.id}].\n"
            f"Текущий next_step: {task.next_step or 'не задан'}\n"
            f"Статус: {task.status}\n\n"
            f"Проверь актуальность задачи. Если нужно действие (напоминание, follow-up) — выполни.\n"
            f"Обнови next_step если он изменился.\n"
            f"Если всё ок — ответь HEARTBEAT_OK."
        )

        content = await session.query(prompt)

        # Сохраняем session_id если изменился
        if session._session_id and session._session_id != task.session_id:
            await repo.update_task_session(task.id, session._session_id)

        if HEARTBEAT_OK_MARKER not in content:
            content = content.replace(HEARTBEAT_OK_MARKER, "").strip()
            if content:
                return f"[{task.id}] {content}"
        return None

    async def _check_user_tasks(self) -> None:
        """Проверяет просроченные задачи и напоминает пользователям."""
        from src.users import get_users_repository

        repo = get_users_repository()

        # Получаем просроченные задачи
        overdue = await repo.list_tasks(overdue_only=True)
        if not overdue:
            return

        logger.info(f"Found {len(overdue)} overdue tasks")

        # Группируем по assignee
        by_user: dict[int, list] = {}
        for task in overdue:
            if task.assignee_id is None:
                continue
            if task.assignee_id not in by_user:
                by_user[task.assignee_id] = []
            by_user[task.assignee_id].append(task)

        # Отправляем напоминания пользователям
        for user_id, tasks in by_user.items():
            # Не напоминаем owner'у через этот механизм
            if settings.is_owner(user_id):
                continue

            user = await repo.get_user(user_id)
            user_name = user.display_name if user else str(user_id)

            # Формируем напоминание
            task_lines = []
            for task in tasks[:3]:  # Максимум 3 задачи в напоминании
                days = (datetime.now().astimezone() - task.deadline).days if task.deadline else 0
                task_lines.append(f"• {task.title[:50]} (просрочено {days} дн.)")

            reminder = "Напоминание о просроченных задачах:\n\n" + "\n".join(task_lines)
            if len(tasks) > 3:
                reminder += f"\n\n...и ещё {len(tasks) - 3} задач(и)"

            try:
                await self._transport.send_message(user_id, reminder)
                logger.info(f"Sent reminder to {user_name}: {len(tasks)} overdue tasks")
            except Exception as e:
                logger.error(f"Failed to send reminder to {user_name}: {e}")

    async def _build_heartbeat_prompt(self) -> str:
        """Формирует промпт для heartbeat с информацией о задачах."""
        from src.users import get_users_repository

        base_prompt = HEARTBEAT_PROMPT.format(interval=self._interval // 60)

        repo = get_users_repository()

        # Просроченные задачи
        overdue = await repo.list_tasks(overdue_only=True)
        # Все активные задачи с дедлайном (для upcoming)
        active = await repo.list_tasks(include_done=False)

        from datetime import timedelta
        now = datetime.now().astimezone()
        cutoff = now + timedelta(hours=24)
        upcoming = [t for t in active if t.deadline and not t.is_overdue and t.deadline <= cutoff]

        task_info = []

        if overdue:
            task_info.append(f"\n## Просроченные задачи ({len(overdue)})")
            for task in overdue[:5]:
                user = await repo.get_user(task.assignee_id) if task.assignee_id else None
                user_name = user.display_name if user else str(task.assignee_id or "система")
                next_step_info = f" → {task.next_step}" if task.next_step else ""
                task_info.append(f"- [{task.id}] {user_name}: {task.title[:40]}{next_step_info} (просрочено)")

        if upcoming:
            task_info.append(f"\n## Задачи на сегодня ({len(upcoming)})")
            for task in upcoming[:5]:
                user = await repo.get_user(task.assignee_id) if task.assignee_id else None
                user_name = user.display_name if user else str(task.assignee_id or "система")
                time_str = task.deadline.strftime("%H:%M") if task.deadline else "—"
                next_step_info = f" → {task.next_step}" if task.next_step else ""
                task_info.append(f"- [{task.id}] {user_name}: {task.title[:40]}{next_step_info} (дедлайн {time_str})")

        # Запланированные задачи (ближайшие schedule_at)
        scheduled = await repo.list_tasks(kind="scheduled")
        scheduled_active = [t for t in scheduled if t.schedule_at is not None]
        scheduled_active.sort(key=lambda t: t.schedule_at)

        if scheduled_active:
            task_info.append(f"\n## Запланированные задачи ({len(scheduled_active)})")
            for task in scheduled_active[:5]:
                time_str = task.schedule_at.strftime("%d.%m %H:%M")
                repeat = f" (повтор: {task.schedule_repeat}с)" if task.schedule_repeat else ""
                task_info.append(f"- [{task.id}] {time_str}{repeat}: {task.title[:40]}")

        if task_info:
            return base_prompt + "\n" + "\n".join(task_info)

        return base_prompt

    async def trigger_now(self) -> None:
        """Запускает проверку немедленно (для тестирования)."""
        await self._check()
