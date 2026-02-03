"""
SessionManager — управление сессиями Claude для разных пользователей.

Каждый пользователь получает свою изолированную сессию:
- Owner (tg_user_id) — полный доступ с owner tools
- External users — ограниченный доступ с external tools
"""

import os
from pathlib import Path
from typing import AsyncIterator

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)
from loguru import logger

from src.config import settings, get_owner_display_name, get_owner_link
from src.tools import create_tools_server, OWNER_ALLOWED_TOOLS, EXTERNAL_ALLOWED_TOOLS
from src.mcp_manager.config import get_mcp_config


class UserSession:
    """
    Сессия Claude для конкретного пользователя.

    Отличия от глобальной сессии:
    - Хранит session_id в отдельном файле
    - Может иметь разные system prompts и tools
    """

    def __init__(
        self,
        telegram_id: int,
        session_dir: Path,
        system_prompt: str,
        is_owner: bool = False,
    ) -> None:
        self.telegram_id = telegram_id
        self.is_owner = is_owner
        self._system_prompt = system_prompt
        self._session_file = session_dir / f"{telegram_id}.session"
        self._session_id: str | None = self._load_session_id()
        self._tools_server = create_tools_server()

    def _load_session_id(self) -> str | None:
        """Загружает session_id из файла."""
        if self._session_file.exists():
            session_id = self._session_file.read_text().strip()
            if session_id:
                logger.debug(f"Loaded session [{self.telegram_id}]: {session_id[:8]}...")
                return session_id
        return None

    def _save_session_id(self, session_id: str) -> None:
        """Сохраняет session_id в файл."""
        self._session_file.parent.mkdir(parents=True, exist_ok=True)
        self._session_file.write_text(session_id)
        logger.debug(f"Saved session [{self.telegram_id}]: {session_id[:8]}...")

    def _build_options(self) -> ClaudeAgentOptions:
        """Создаёт опции для клиента."""
        env = os.environ.copy()
        env["HTTP_PROXY"] = settings.http_proxy
        env["HTTPS_PROXY"] = settings.http_proxy

        if settings.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = settings.anthropic_api_key

        # MCP серверы
        mcp_servers = {"jobs": self._tools_server}

        # Owner получает внешние MCP серверы
        if self.is_owner:
            mcp_config = get_mcp_config()
            external_servers = mcp_config.to_mcp_json()
            mcp_servers.update(external_servers)

        # Разные allowed_tools для owner и external users
        allowed_tools = OWNER_ALLOWED_TOOLS if self.is_owner else EXTERNAL_ALLOWED_TOOLS

        # Owner имеет полный доступ, external users — ограниченный
        permission_mode = "bypassPermissions" if self.is_owner else "default"

        options = ClaudeAgentOptions(
            model=settings.claude_model,
            cwd=Path(settings.workspace_dir),
            permission_mode=permission_mode,
            env=env,
            mcp_servers=mcp_servers,
            allowed_tools=allowed_tools,
            system_prompt=self._system_prompt,
        )

        if self._session_id:
            options.resume = self._session_id

        return options

    async def query(self, prompt: str) -> str:
        """Отправляет запрос и возвращает ответ."""
        options = self._build_options()
        text_parts: list[str] = []

        try:
            async with ClaudeSDKClient(options=options) as client:
                await client.query(prompt)

                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                text_parts.append(block.text)

                    elif isinstance(message, ResultMessage):
                        if message.session_id:
                            self._session_id = message.session_id
                            self._save_session_id(message.session_id)

        except Exception as e:
            logger.error(f"Claude error [{self.telegram_id}]: {e}")
            return f"❌ Ошибка: {e}"

        return "".join(text_parts) or "🤷 Нет ответа"

    async def query_stream(self, prompt: str) -> AsyncIterator[tuple[str | None, str | None, bool]]:
        """
        Стримит ответ.

        Yields:
            (text, tool_name, is_final)
        """
        options = self._build_options()
        text_buffer: list[str] = []

        try:
            async with ClaudeSDKClient(options=options) as client:
                await client.query(prompt)

                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                text_buffer.append(block.text)
                                yield (block.text, None, False)
                            elif isinstance(block, ToolUseBlock):
                                yield (None, block.name, False)

                    elif isinstance(message, ResultMessage):
                        if message.session_id:
                            self._session_id = message.session_id
                            self._save_session_id(message.session_id)

                        yield ("".join(text_buffer), None, True)

        except Exception as e:
            logger.error(f"Claude error [{self.telegram_id}]: {e}")
            yield (f"❌ Ошибка: {e}", None, True)

    def reset(self) -> None:
        """Сбрасывает сессию."""
        self._session_id = None
        if self._session_file.exists():
            self._session_file.unlink()
        logger.info(f"Session reset [{self.telegram_id}]")


class SessionManager:
    """
    Менеджер сессий — создаёт и хранит сессии по telegram_id.
    """

    def __init__(self, session_dir: Path) -> None:
        self._session_dir = session_dir
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[int, UserSession] = {}

        # Lazy imports для промптов
        self._owner_prompt: str | None = None
        self._external_prompt_template: str | None = None

    def _get_owner_prompt(self) -> str:
        """Загружает system prompt для owner'а."""
        if self._owner_prompt is None:
            from src.users.prompts import OWNER_SYSTEM_PROMPT
            self._owner_prompt = OWNER_SYSTEM_PROMPT
        return self._owner_prompt

    def _get_external_prompt(self, user_display_name: str) -> str:
        """Загружает system prompt для внешнего пользователя."""
        if self._external_prompt_template is None:
            from src.users.prompts import EXTERNAL_USER_PROMPT_TEMPLATE
            self._external_prompt_template = EXTERNAL_USER_PROMPT_TEMPLATE

        # Формируем контактную информацию
        owner_link = get_owner_link()
        if owner_link:
            contact_info = f"Ссылка на владельца: {owner_link}"
        else:
            contact_info = "Прямой контакт недоступен, только через бота."

        return self._external_prompt_template.format(
            username=user_display_name,
            owner_name=get_owner_display_name(),
            owner_contact_info=contact_info,
        )

    def get_session(self, telegram_id: int, user_display_name: str | None = None) -> UserSession:
        """
        Получает или создаёт сессию для пользователя.

        Args:
            telegram_id: ID пользователя в Telegram
            user_display_name: Имя пользователя для промпта (для external users)
        """
        if telegram_id in self._sessions:
            return self._sessions[telegram_id]

        is_owner = telegram_id == settings.tg_user_id

        if is_owner:
            system_prompt = self._get_owner_prompt()
        else:
            system_prompt = self._get_external_prompt(user_display_name or str(telegram_id))

        session = UserSession(
            telegram_id=telegram_id,
            session_dir=self._session_dir,
            system_prompt=system_prompt,
            is_owner=is_owner,
        )

        self._sessions[telegram_id] = session
        logger.info(f"Created session for {telegram_id} (owner={is_owner})")

        return session

    def get_owner_session(self) -> UserSession:
        """Shortcut для получения сессии owner'а."""
        return self.get_session(settings.tg_user_id)

    def reset_session(self, telegram_id: int) -> None:
        """Сбрасывает сессию пользователя."""
        if telegram_id in self._sessions:
            self._sessions[telegram_id].reset()
            del self._sessions[telegram_id]

    def reset_all(self) -> None:
        """Сбрасывает все сессии."""
        for session in self._sessions.values():
            session.reset()
        self._sessions.clear()
        logger.info("All sessions reset")


# Singleton
_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """Возвращает глобальный менеджер сессий."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager(settings.sessions_dir)
    return _session_manager
