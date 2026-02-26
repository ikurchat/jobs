"""
Whitelist — реестр получателей исходящих сообщений.

Все инструменты отправки (tg_send_message, send_to_user, create_task)
доступны только owner-сессиям, поэтому whitelist работает как реестр,
а не блокировщик: при первом контакте автоматически добавляет получателя
в список и логирует.
"""

from loguru import logger
from telethon.tl.types import User, Channel, Chat

from src.config import settings
from src.users.repository import get_users_repository


async def _auto_whitelist(user_id: int, username: str | None = None) -> None:
    """Автоматически добавляет пользователя в whitelist при первом контакте."""
    repo = get_users_repository()
    user = await repo.get_user(user_id)
    if user is None:
        await repo.upsert_user(telegram_id=user_id, username=username)
    if not (user and user.is_whitelisted):
        await repo.whitelist_user(user_id)
        tag = f" (@{username})" if username else ""
        logger.info(f"Auto-whitelisted user_id={user_id}{tag} on first outgoing contact")


async def validate_recipient(entity) -> tuple[bool, str]:
    """
    Валидирует получателя. Автоматически добавляет в whitelist при первом контакте.

    Returns:
        (allowed, reason)
    """
    if isinstance(entity, User) and settings.is_owner(entity.id):
        return True, "owner"

    if isinstance(entity, (Channel, Chat)):
        return True, "channel/group"

    if isinstance(entity, User):
        repo = get_users_repository()
        if not await repo.is_user_whitelisted(entity.id):
            await _auto_whitelist(entity.id, entity.username)
        return True, "whitelisted"

    entity_id = getattr(entity, "id", "unknown")
    logger.warning(f"Unknown entity type: {type(entity).__name__} (id={entity_id})")
    return True, f"unknown entity type (allowed): {type(entity).__name__}"


async def validate_recipient_by_id(user_id: int) -> tuple[bool, str]:
    """
    Валидирует по user_id. Автоматически добавляет в whitelist при первом контакте.

    Returns:
        (allowed, reason)
    """
    if settings.is_owner(user_id):
        return True, "owner"

    repo = get_users_repository()
    if not await repo.is_user_whitelisted(user_id):
        await _auto_whitelist(user_id)

    return True, "whitelisted"
