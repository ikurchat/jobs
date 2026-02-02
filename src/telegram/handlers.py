from telethon import TelegramClient, events
from telegraph import Telegraph
from loguru import logger

from src.config import settings
from src.claude.runner import run_claude

MAX_TG_LENGTH = 4000  # Оставляем запас до лимита 4096


class TelegramHandlers:
    """Обработчики сообщений Telegram."""

    def __init__(self, client: TelegramClient):
        self.client = client
        self.telegraph = Telegraph()
        self._telegraph_initialized = False

    def _ensure_telegraph(self) -> None:
        """Ленивая инициализация Telegraph аккаунта."""
        if not self._telegraph_initialized:
            self.telegraph.create_account(short_name="JobsBot")
            self._telegraph_initialized = True

    def register(self) -> None:
        """Регистрирует обработчики событий."""
        self.client.add_event_handler(
            self._handle_message,
            events.NewMessage(from_users=[settings.tg_user_id]),
        )
        logger.info(f"Registered message handler for user {settings.tg_user_id}")

    async def _handle_message(self, event: events.NewMessage.Event) -> None:
        """Обрабатывает входящее сообщение."""
        message = event.message
        prompt = message.text

        if not prompt:
            return

        logger.info(f"Received message: {prompt[:100]}...")

        # Отправляем статус
        status_msg = await event.reply("⏳ Работаю...")

        # Запускаем Claude
        response = await run_claude(prompt)

        if response.is_error:
            await status_msg.edit(f"❌ {response.content}")
            return

        # Обрабатываем ответ
        content = response.content

        if len(content) > MAX_TG_LENGTH:
            # Длинный ответ → Telegraph
            url = self._publish_to_telegraph(prompt, content)
            cost_info = f"\n\n💰 ${response.cost_usd:.4f}" if response.cost_usd else ""
            await status_msg.edit(f"📄 Готово: {url}{cost_info}")
        else:
            cost_info = f"\n\n💰 ${response.cost_usd:.4f}" if response.cost_usd else ""
            await status_msg.edit(f"{content}{cost_info}")

    def _publish_to_telegraph(self, title: str, content: str) -> str:
        """Публикует контент в Telegraph и возвращает URL."""
        self._ensure_telegraph()

        # Формируем заголовок из первых 50 символов промпта
        short_title = title[:50] + "..." if len(title) > 50 else title

        # Экранируем HTML и оборачиваем в pre для сохранения форматирования
        safe_content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        html_content = f"<pre>{safe_content}</pre>"

        page = self.telegraph.create_page(
            title=short_title,
            html_content=html_content,
        )

        return page["url"]
