"""
Whitelist — реестр получателей исходящих сообщений.

Бот может отправлять DM только:
- Owner'у
- Пользователям в whitelist (добавляются через whitelist_user tool)
- Каналам/группам

Попытка отправить не-whitelisted пользователю блокируется.
"""

from loguru import logger
from telethon.tl.types import User, Channel, Chat

from src.config import settings
from src.users.repository import get_users_repository


async def validate_recipient(entity) -> tuple[bool, str]:
    """
    Валидирует получателя. НЕ whitelisted пользователи блокируются.

    Returns:
        (allowed, reason)
    """
    if isinstance(entity, User) and settings.is_owner(entity.id):
        return True, "owner"

    if isinstance(entity, (Channel, Chat)):
        return True, "channel/group"

    if isinstance(entity, User):
        repo = get_users_repository()
        if await repo.is_user_whitelisted(entity.id):
            return True, "whitelisted"
        tag = f" (@{entity.username})" if entity.username else ""
        logger.warning(f"BLOCKED outgoing to user_id={entity.id}{tag}: not in whitelist")
        return False, f"User {entity.id}{tag} not in whitelist. Use whitelist_user() first."

    entity_id = getattr(entity, "id", "unknown")
    logger.warning(f"Unknown entity type: {type(entity).__name__} (id={entity_id})")
    return False, f"Unknown entity type: {type(entity).__name__}"


async def validate_recipient_by_id(user_id: int) -> tuple[bool, str]:
    """
    Валидирует по user_id. НЕ whitelisted пользователи блокируются.

    Returns:
        (allowed, reason)
    """
    if settings.is_owner(user_id):
        return True, "owner"

    repo = get_users_repository()
    if await repo.is_user_whitelisted(user_id):
        return True, "whitelisted"

    logger.warning(f"BLOCKED outgoing to user_id={user_id}: not in whitelist")
    return False, f"User {user_id} not in whitelist. Use whitelist_user() first."
