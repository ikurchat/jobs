import asyncio
import sys

from loguru import logger

from src.config import settings
from src.telegram.client import create_client, load_session_string, save_session_string
from src.telegram.auth import interactive_auth
from src.telegram.handlers import TelegramHandlers


def setup_logging() -> None:
    """Настройка логирования."""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level="DEBUG",
    )


async def main() -> None:
    """Точка входа."""
    setup_logging()

    logger.info("Starting Jobs - Personal AI Assistant")
    logger.info(f"Data directory: {settings.data_dir}")
    logger.info(f"Workspace: {settings.workspace_dir}")

    # Создаём директории
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)

    # Загружаем сессию
    session_string = load_session_string()
    client = create_client(session_string)

    # Авторизация
    try:
        await client.connect()

        if not await client.is_user_authorized():
            logger.info("Требуется авторизация в Telegram")
            await interactive_auth(client)
            # Перезагружаем клиент с новой сессией
            session_string = load_session_string()
            await client.disconnect()
            client = create_client(session_string)
            await client.connect()

        me = await client.get_me()
        logger.info(f"Logged in as {me.first_name} (ID: {me.id})")

        # Проверяем, что tg_user_id совпадает
        if me.id != settings.tg_user_id:
            logger.warning(
                f"Logged in user ID ({me.id}) != configured TG_USER_ID ({settings.tg_user_id})"
            )
            logger.warning("Бот будет отвечать только на сообщения от TG_USER_ID")

    except Exception as e:
        logger.error(f"Ошибка авторизации: {e}")
        raise

    # Регистрируем обработчики
    handlers = TelegramHandlers(client)
    handlers.register()

    logger.info("Bot is running. Send me a message!")

    # Запускаем event loop
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
