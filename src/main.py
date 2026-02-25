"""
Jobs — Personal AI Assistant.

Точка входа приложения.
"""

import asyncio
import shutil
import sys
from pathlib import Path

from loguru import logger

# Patch SDK to handle rate_limit_event gracefully.
# SDK v0.1.39 raises MessageParseError for unknown message types, but
# rate_limit_event is a normal informational event from Claude CLI (not fatal).
# Without this patch the entire response stream is aborted on rate_limit_event.
def _patch_sdk_message_parser() -> None:
    from claude_agent_sdk._internal import client as _sdk_client
    from claude_agent_sdk._internal import message_parser as _sdk_mp
    from claude_agent_sdk._internal.message_parser import parse_message as _orig
    from claude_agent_sdk.types import SystemMessage

    def _patched_parse(data: dict) -> object:
        if isinstance(data, dict) and data.get("type") == "rate_limit_event":
            return SystemMessage(subtype="rate_limit_event", data=data)
        return _orig(data)

    # Patch both locations:
    # 1. _internal/client.py imports parse_message at module level
    _sdk_client.parse_message = _patched_parse
    # 2. public client.py does `from ._internal.message_parser import parse_message`
    #    inside receive_messages() at runtime
    _sdk_mp.parse_message = _patched_parse

_patch_sdk_message_parser()

from src.config import settings, set_owner_info
from src.telegram.client import create_client, load_session_string
from src.telegram.handlers import TelegramHandlers
from src.telegram.tools import set_telegram_client
from src.setup import run_setup, is_telegram_configured, is_claude_configured
from src.tools.scheduler import SchedulerRunner
from src.users import get_session_manager
from src.memory import get_storage
from src.heartbeat import HeartbeatRunner
from src.triggers import TriggerExecutor, TriggerManager, set_trigger_manager
from src.triggers.sources.tg_channel import TelegramChannelTrigger
from src.updater import Updater, AUTO_CHECK_INTERVAL


CLAUDE_JSON = Path("/home/jobs/.claude.json")
CLAUDE_BACKUPS = Path("/home/jobs/.claude/backups")


def _restore_claude_json_if_needed() -> None:
    """Восстанавливает .claude.json из бэкапа, если файла нет (SDK ищет его при старте)."""
    if CLAUDE_JSON.exists():
        return
    if not CLAUDE_BACKUPS.is_dir():
        return
    backups = sorted(CLAUDE_BACKUPS.glob(".claude.json.backup.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        return
    shutil.copy(backups[0], CLAUDE_JSON)
    logger.info(f"Restored {CLAUDE_JSON} from backup")


def setup_logging() -> None:
    """Настраивает логирование."""
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

    # Инициализируем память (создаёт структуру файлов)
    memory_storage = get_storage()
    logger.info(f"Memory initialized at {settings.workspace_dir}")

    # Восстановить .claude.json из бэкапа, если SDK его ожидает
    _restore_claude_json_if_needed()

    # Setup при первом запуске
    if not is_telegram_configured() or not is_claude_configured():
        logger.info("Требуется первоначальная настройка")
        if not await run_setup():
            logger.error("Setup не завершён")
            sys.exit(1)

    # Создаём клиент
    session_string = load_session_string()
    client = create_client(session_string)
    set_telegram_client(client)  # Для Telegram tools

    try:
        await client.connect()

        if not await client.is_user_authorized():
            logger.error("Telegram сессия невалидна. Удалите data/telethon.session")
            sys.exit(1)

        me = await client.get_me()
        logger.info(f"Logged in as {me.first_name} (ID: {me.id})")

        # Загружаем диалоги в кэш и получаем инфо о owner'е
        await client.get_dialogs()
        try:
            owner = await client.get_entity(settings.tg_user_id)
            set_owner_info(
                telegram_id=settings.tg_user_id,
                first_name=owner.first_name,
                username=owner.username,
            )
            logger.info(f"Owner: {owner.first_name} @{owner.username} (ID: {settings.tg_user_id})")
        except Exception as e:
            logger.warning(f"Could not get owner info: {e}. Write to bot first.")
            set_owner_info(settings.tg_user_id, None, None)

        if me.id != settings.tg_user_id:
            logger.warning(f"Logged user {me.id} != TG_USER_ID {settings.tg_user_id}")

    except Exception as e:
        logger.error(f"Connection error: {e}")
        raise

    # Unified Trigger System
    session_manager = get_session_manager()
    executor = TriggerExecutor(client, session_manager)
    trigger_manager = TriggerManager(executor, client, str(settings.db_path))

    # Регистрируем типы динамических триггеров
    trigger_manager.register_type("tg_channel", TelegramChannelTrigger)

    # Регистрируем встроенные
    scheduler = SchedulerRunner(executor=executor)
    trigger_manager.register_builtin("scheduler", scheduler)

    if settings.heartbeat_interval_minutes > 0:
        heartbeat = HeartbeatRunner(
            executor=executor,
            client=client,
            session_manager=session_manager,
            interval_minutes=settings.heartbeat_interval_minutes,
        )
        trigger_manager.register_builtin("heartbeat", heartbeat)
    else:
        logger.info("Heartbeat disabled (interval=0)")

    # Устанавливаем singleton для trigger tools
    set_trigger_manager(trigger_manager)

    # Запуск (builtins + загрузка подписок из DB)
    await trigger_manager.start_all()

    # Регистрируем handlers (интерактивный Telegram — отдельно)
    handlers = TelegramHandlers(client, executor)
    handlers.register()
    await handlers.on_startup()

    # Автопроверка обновлений
    async def _auto_check_updates() -> None:
        updater = Updater()
        while True:
            await asyncio.sleep(AUTO_CHECK_INTERVAL)
            try:
                text = await updater.check_for_notification()
                if text:
                    await client.send_message(settings.tg_user_id, text)
            except Exception as e:
                logger.debug(f"Auto update check failed: {e}")

    asyncio.create_task(_auto_check_updates())

    logger.info("Bot is running. Send me a message!")

    try:
        await client.run_until_disconnected()
    finally:
        await trigger_manager.stop_all()


if __name__ == "__main__":
    asyncio.run(main())
