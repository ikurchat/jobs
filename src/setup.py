import asyncio
import subprocess
import sys
from pathlib import Path

from loguru import logger

from src.config import settings
from src.telegram.client import create_client, load_session_string, save_session_string
from src.telegram.auth import interactive_auth


CLAUDE_CONFIG_DIR = Path.home() / ".claude"
CLAUDE_CREDENTIALS_FILE = CLAUDE_CONFIG_DIR / "credentials.json"
# Альтернативные пути где Claude может хранить auth
CLAUDE_AUTH_FILES = [
    CLAUDE_CONFIG_DIR / "credentials.json",
    CLAUDE_CONFIG_DIR / ".credentials.json",
    CLAUDE_CONFIG_DIR / "settings.json",
]


def is_telegram_configured() -> bool:
    """Проверяет, есть ли сохранённая Telegram сессия."""
    session_string = load_session_string()
    return session_string is not None and len(session_string) > 0


def is_claude_configured() -> bool:
    """Проверяет, есть ли credentials для Claude Code."""
    return any(f.exists() for f in CLAUDE_AUTH_FILES)


def setup_claude_interactive() -> bool:
    """
    Запускает Claude Code интерактивно для OAuth логина.
    Возвращает True если логин успешен.
    """
    logger.info("Запуск Claude Code для авторизации...")
    logger.info("Откроется браузер для входа в Anthropic Console")
    logger.info("После входа вернитесь в терминал и нажмите Ctrl+C")
    print()

    env = {
        **dict(__import__("os").environ),
        "HTTP_PROXY": settings.http_proxy,
        "HTTPS_PROXY": settings.http_proxy,
    }

    # Запускаем claude интерактивно
    # Пользователь должен залогиниться через браузер
    proc = subprocess.run(
        ["claude"],
        env=env,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    # Проверяем что credentials появились
    if is_claude_configured():
        logger.info("✅ Claude Code авторизован успешно!")
        return True
    else:
        logger.warning("❌ Credentials не найдены после входа")
        return False


async def setup_telegram() -> bool:
    """Настраивает Telegram клиент."""
    session_string = load_session_string()
    client = create_client(session_string)

    try:
        was_authorized = await interactive_auth(client)
        if not was_authorized:
            logger.info("Telegram уже авторизован")
        return True
    except Exception as e:
        logger.error(f"Ошибка авторизации Telegram: {e}")
        return False
    finally:
        await client.disconnect()


async def run_setup() -> bool:
    """
    Запускает полный setup flow.
    Возвращает True если всё настроено успешно.
    """
    print("=" * 50)
    print("🚀 Jobs Setup - Первоначальная настройка")
    print("=" * 50)
    print()

    # Создаём директории
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)

    # Шаг 1: Telegram
    print("📱 Шаг 1/2: Настройка Telegram")
    print("-" * 30)

    if is_telegram_configured():
        # Проверяем что сессия валидна
        session_string = load_session_string()
        client = create_client(session_string)
        try:
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me()
                logger.info(f"Telegram уже настроен: {me.first_name} (ID: {me.id})")
            else:
                logger.info("Сессия невалидна, требуется повторный вход")
                await setup_telegram()
        finally:
            await client.disconnect()
    else:
        success = await setup_telegram()
        if not success:
            logger.error("Не удалось настроить Telegram")
            return False

    print()

    # Шаг 2: Claude Code
    print("🤖 Шаг 2/2: Настройка Claude Code")
    print("-" * 30)

    if is_claude_configured():
        logger.info("Claude Code уже настроен")
    else:
        success = setup_claude_interactive()
        if not success:
            logger.error("Не удалось настроить Claude Code")
            return False

    print()
    print("=" * 50)
    print("✅ Setup завершён успешно!")
    print("=" * 50)

    return True
