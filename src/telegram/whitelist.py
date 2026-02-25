"""
Whitelist — централизованная валидация получателей исходящих сообщений.

Бот может отправлять сообщения ТОЛЬКО:
- Owner (settings.is_owner()) — всегда
- Каналы / группы — всегда (не DM)
- Пользователи с is_whitelisted=True в БД
"""

from loguru import logger
from telethon.tl.types import User, Channel, Chat

from src.config import settings
from src.users.repository import get_users_repository


async def validate_recipient(entity) -> tuple[bool, str]:
    """
    Проверяет, разрешена ли отправка сообщения данному получателю.

    Returns:
        (allowed, reason) — разрешено ли + причина блокировки/разрешения
    """
    # Owner — всегда разрешён
    if isinstance(entity, User) and settings.is_owner(entity.id):
        return True, "owner"

    # Каналы и группы — разрешены (не DM)
    if isinstance(entity, (Channel, Chat)):
        return True, "channel/group"

    # Пользователь — проверяем whitelist в БД
    if isinstance(entity, User):
        repo = get_users_repository()
        if await repo.is_user_whitelisted(entity.id):
            return True, "whitelisted"
        logger.warning(
            f"BLOCKED outgoing message to user {entity.id} "
            f"(@{entity.username or 'no_username'}) — not whitelisted"
        )
        return False, f"User {entity.id} (@{entity.username or 'no_username'}) is not whitelisted"

    # Неизвестный тип — блокируем на всякий случай
    entity_id = getattr(entity, "id", "unknown")
    logger.warning(f"BLOCKED outgoing message to unknown entity type: {type(entity).__name__} (id={entity_id})")
    return False, f"Unknown entity type: {type(entity).__name__}"


async def validate_recipient_by_id(user_id: int) -> tuple[bool, str]:
    """
    Проверяет по user_id (без entity). Для _send_message и heartbeat.

    Returns:
        (allowed, reason)
    """
    # Owner — всегда
    if settings.is_owner(user_id):
        return True, "owner"

    repo = get_users_repository()
    if await repo.is_user_whitelisted(user_id):
        return True, "whitelisted"

    logger.warning(f"BLOCKED outgoing message to user_id={user_id} — not whitelisted")
    return False, f"User {user_id} is not whitelisted. Use whitelist_user() to approve."
