"""
TriggerExecutor — единая точка выполнения TriggerEvent.

Принимает событие, отправляет preview, запрашивает агента,
проверяет silent_marker, доставляет результат owner'у.

Каждое выполнение получает одноразовую сессию —
параллельные задачи не блокируют друг друга и не прерывают owner.
"""

from loguru import logger
from telethon import TelegramClient

from src.config import settings
from src.triggers.models import TriggerEvent
from src.users.session_manager import SessionManager


MAX_MESSAGE_LENGTH = 4000


class TriggerExecutor:
    """Выполняет TriggerEvent: query → deliver."""

    def __init__(self, client: TelegramClient, session_manager: SessionManager) -> None:
        self._client = client
        self._session_manager = session_manager

    async def execute(self, event: TriggerEvent) -> str | None:
        """
        Выполняет событие триггера в одноразовой сессии.

        1. Отправляет preview_message owner'у (если есть)
        2. Запрашивает агента через ephemeral background session
        3. Проверяет silent_marker — если есть, не доставляет
        4. Добавляет result_prefix, truncate, отправляет owner'у

        Returns:
            Ответ агента или None (если silent).
        """
        logger.debug(f"Executing trigger event: {event.source}")

        # Preview (без буферизации — это просто уведомление)
        if event.preview_message and event.notify_owner:
            await self.send_to_owner(event.preview_message, buffer=False)

        # Одноразовая сессия с owner tools
        session = self._session_manager.create_background_session()
        try:
            content = await session.query(event.prompt)
        finally:
            await session.destroy()

        content = content.strip()

        # Silent marker check
        if event.silent_marker and event.silent_marker in content:
            logger.debug(f"Trigger {event.source}: silent ({event.silent_marker})")
            return None

        # Prepare result
        if event.silent_marker:
            content = content.replace(event.silent_marker, "").strip()

        if not content:
            return None

        if event.result_prefix:
            content = f"{event.result_prefix}\n{content}"

        # Truncate
        if len(content) > MAX_MESSAGE_LENGTH:
            content = content[:MAX_MESSAGE_LENGTH] + "..."

        # Deliver
        if event.notify_owner:
            await self.send_to_owner(content)

        return content

    async def send_to_owner(self, text: str, buffer: bool = True) -> None:
        """
        Отправляет сообщение owner'у.

        Args:
            text: текст сообщения
            buffer: буферизовать в owner session (для сохранения контекста)
        """
        await self._client.send_message(settings.tg_user_id, text)

        # Буферизуем в owner session чтобы сохранить контекст
        if buffer:
            owner_session = self._session_manager.get_session(settings.tg_user_id)
            owner_session.receive_incoming(f"[Background task output]\n{text}")
