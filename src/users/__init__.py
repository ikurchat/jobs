"""
Users Module — управление внешними пользователями и их задачами.
"""

from .models import ExternalUser, UserTask
from .repository import UsersRepository, get_users_repository
from .session_manager import SessionManager, get_session_manager

__all__ = [
    "ExternalUser",
    "UserTask",
    "UsersRepository",
    "get_users_repository",
    "SessionManager",
    "get_session_manager",
]
