"""
Plugin Config — хранение конфигурации установленных плагинов.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from src.config import settings


@dataclass
class InstalledPlugin:
    """Установленный плагин."""
    name: str
    path: str  # Путь к директории плагина
    enabled: bool = True

    # Метаданные из plugin.json
    description: str = ""
    author_name: str = ""
    author_email: str = ""

    def to_sdk_format(self) -> dict[str, Any]:
        """Конвертирует в формат для ClaudeAgentOptions.plugins."""
        return {
            "type": "local",
            "path": self.path,
        }


@dataclass
class PluginConfig:
    """Конфигурация всех плагинов."""
    plugins: dict[str, InstalledPlugin] = field(default_factory=dict)

    def add_plugin(
        self,
        name: str,
        path: str,
        description: str = "",
        author_name: str = "",
        author_email: str = "",
    ) -> None:
        """Добавляет плагин."""
        self.plugins[name] = InstalledPlugin(
            name=name,
            path=path,
            enabled=True,
            description=description,
            author_name=author_name,
            author_email=author_email,
        )
        logger.info(f"Added plugin: {name}")

    def remove_plugin(self, name: str) -> bool:
        """Удаляет плагин."""
        if name in self.plugins:
            del self.plugins[name]
            logger.info(f"Removed plugin: {name}")
            return True
        return False

    def enable_plugin(self, name: str) -> bool:
        """Включает плагин."""
        if name in self.plugins:
            self.plugins[name].enabled = True
            logger.info(f"Enabled plugin: {name}")
            return True
        return False

    def disable_plugin(self, name: str) -> bool:
        """Отключает плагин."""
        if name in self.plugins:
            self.plugins[name].enabled = False
            logger.info(f"Disabled plugin: {name}")
            return True
        return False

    def get_enabled_plugins(self) -> list[InstalledPlugin]:
        """Возвращает только включённые плагины."""
        return [p for p in self.plugins.values() if p.enabled]

    def to_sdk_format(self) -> list[dict[str, Any]]:
        """
        Конвертирует в формат для ClaudeAgentOptions.plugins.

        Returns:
            Список плагинов в SDK формате
        """
        return [p.to_sdk_format() for p in self.get_enabled_plugins()]

    def list_plugins(self) -> list[dict[str, Any]]:
        """Список плагинов для отображения."""
        return [
            {
                "name": name,
                "enabled": p.enabled,
                "description": p.description[:100] if p.description else "",
                "author": p.author_name,
            }
            for name, p in self.plugins.items()
        ]


class PluginConfigStorage:
    """Хранилище конфигурации в JSON файле."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> PluginConfig:
        """Загружает конфигурацию."""
        if not self._path.exists():
            return PluginConfig()

        try:
            data = json.loads(self._path.read_text())
            plugins = {}
            for name, plugin_data in data.get("plugins", {}).items():
                plugins[name] = InstalledPlugin(
                    name=name,
                    path=plugin_data.get("path", ""),
                    enabled=plugin_data.get("enabled", True),
                    description=plugin_data.get("description", ""),
                    author_name=plugin_data.get("author_name", ""),
                    author_email=plugin_data.get("author_email", ""),
                )
            return PluginConfig(plugins=plugins)
        except Exception as e:
            logger.error(f"Failed to load plugin config: {e}")
            return PluginConfig()

    def save(self, config: PluginConfig) -> None:
        """Сохраняет конфигурацию."""
        data = {
            "plugins": {
                name: {
                    "path": p.path,
                    "enabled": p.enabled,
                    "description": p.description,
                    "author_name": p.author_name,
                    "author_email": p.author_email,
                }
                for name, p in config.plugins.items()
            }
        }

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.debug(f"Saved plugin config to {self._path}")


# Singleton
_storage: PluginConfigStorage | None = None
_config: PluginConfig | None = None


def get_plugin_config() -> PluginConfig:
    """Возвращает глобальную конфигурацию."""
    global _storage, _config
    if _storage is None:
        _storage = PluginConfigStorage(settings.data_dir / "plugins.json")
        _config = _storage.load()
    return _config


def save_plugin_config() -> None:
    """Сохраняет глобальную конфигурацию."""
    global _storage, _config
    if _storage and _config:
        _storage.save(_config)
