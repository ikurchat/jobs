"""
MCP Config — хранение конфигурации подключённых серверов.

Формат конфига совместим с Claude Code (.mcp.json).
"""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from loguru import logger

from src.config import settings


@dataclass
class MCPServerConfig:
    """Конфигурация одного MCP сервера."""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True

    # Метаданные
    title: str = ""
    description: str = ""
    source: str = "manual"  # manual, registry

    def to_mcp_json(self) -> dict[str, Any]:
        """Конвертирует в формат .mcp.json."""
        return {
            "command": self.command,
            "args": self.args,
            "env": self.env,
        }


@dataclass
class MCPConfig:
    """Конфигурация всех MCP серверов."""
    servers: dict[str, MCPServerConfig] = field(default_factory=dict)

    def add_server(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        title: str = "",
        description: str = "",
        source: str = "manual",
    ) -> None:
        """Добавляет сервер."""
        self.servers[name] = MCPServerConfig(
            name=name,
            command=command,
            args=args or [],
            env=env or {},
            enabled=True,
            title=title or name,
            description=description,
            source=source,
        )
        logger.info(f"Added MCP server: {name}")

    def remove_server(self, name: str) -> bool:
        """Удаляет сервер."""
        if name in self.servers:
            del self.servers[name]
            logger.info(f"Removed MCP server: {name}")
            return True
        return False

    def enable_server(self, name: str) -> bool:
        """Включает сервер."""
        if name in self.servers:
            self.servers[name].enabled = True
            logger.info(f"Enabled MCP server: {name}")
            return True
        return False

    def disable_server(self, name: str) -> bool:
        """Отключает сервер."""
        if name in self.servers:
            self.servers[name].enabled = False
            logger.info(f"Disabled MCP server: {name}")
            return True
        return False

    def set_env(self, name: str, key: str, value: str) -> bool:
        """Устанавливает env переменную для сервера."""
        if name in self.servers:
            self.servers[name].env[key] = value
            logger.debug(f"Set {name}.env.{key}")
            return True
        return False

    def get_enabled_servers(self) -> dict[str, MCPServerConfig]:
        """Возвращает только включённые серверы."""
        return {
            name: server
            for name, server in self.servers.items()
            if server.enabled
        }

    def to_mcp_json(self) -> dict[str, Any]:
        """
        Конвертирует в формат .mcp.json для Claude.

        Returns:
            Словарь совместимый с mcpServers конфигурацией
        """
        return {
            name: server.to_mcp_json()
            for name, server in self.get_enabled_servers().items()
        }

    def list_servers(self) -> list[dict[str, Any]]:
        """Список серверов для отображения."""
        return [
            {
                "name": name,
                "title": s.title,
                "enabled": s.enabled,
                "command": s.command,
                "description": s.description[:100] if s.description else "",
            }
            for name, s in self.servers.items()
        ]


class MCPConfigStorage:
    """Хранилище конфигурации в JSON файле."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> MCPConfig:
        """Загружает конфигурацию."""
        if not self._path.exists():
            return MCPConfig()

        try:
            data = json.loads(self._path.read_text())
            servers = {}
            for name, server_data in data.get("servers", {}).items():
                servers[name] = MCPServerConfig(
                    name=name,
                    command=server_data.get("command", ""),
                    args=server_data.get("args", []),
                    env=server_data.get("env", {}),
                    enabled=server_data.get("enabled", True),
                    title=server_data.get("title", name),
                    description=server_data.get("description", ""),
                    source=server_data.get("source", "manual"),
                )
            return MCPConfig(servers=servers)
        except Exception as e:
            logger.error(f"Failed to load MCP config: {e}")
            return MCPConfig()

    def save(self, config: MCPConfig) -> None:
        """Сохраняет конфигурацию."""
        data = {
            "servers": {
                name: {
                    "command": s.command,
                    "args": s.args,
                    "env": s.env,
                    "enabled": s.enabled,
                    "title": s.title,
                    "description": s.description,
                    "source": s.source,
                }
                for name, s in config.servers.items()
            }
        }

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.debug(f"Saved MCP config to {self._path}")


# Singleton
_storage: MCPConfigStorage | None = None
_config: MCPConfig | None = None


def get_mcp_config() -> MCPConfig:
    """Возвращает глобальную конфигурацию."""
    global _storage, _config
    if _storage is None:
        _storage = MCPConfigStorage(settings.data_dir / "mcp_servers.json")
        _config = _storage.load()
    return _config


def save_mcp_config() -> None:
    """Сохраняет глобальную конфигурацию."""
    global _storage, _config
    if _storage and _config:
        _storage.save(_config)
