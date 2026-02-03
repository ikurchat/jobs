"""
Plugin Registry — сканирование доступных плагинов из маркетплейсов.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from src.config import settings


@dataclass
class PluginInfo:
    """Информация о плагине из маркетплейса."""
    name: str
    path: str  # Полный путь к директории плагина
    description: str = ""
    author_name: str = ""
    author_email: str = ""

    # Содержимое плагина
    has_skills: bool = False
    has_commands: bool = False
    has_hooks: bool = False
    has_agents: bool = False
    has_mcp: bool = False


class PluginRegistry:
    """Реестр доступных плагинов."""

    def __init__(self, claude_dir: Path | None = None):
        # В Docker: /home/jobs/.claude (через settings)
        # На хосте: data/.claude (монтируется)
        self._claude_dir = claude_dir or Path(settings.claude_dir)
        self._plugins_dir = self._claude_dir / "plugins" / "marketplaces"

    def _scan_plugin(self, plugin_dir: Path) -> PluginInfo | None:
        """Сканирует один плагин."""
        plugin_json = plugin_dir / ".claude-plugin" / "plugin.json"

        if not plugin_json.exists():
            return None

        try:
            data = json.loads(plugin_json.read_text())

            author = data.get("author", {})

            return PluginInfo(
                name=data.get("name", plugin_dir.name),
                path=str(plugin_dir),
                description=data.get("description", ""),
                author_name=author.get("name", "") if isinstance(author, dict) else "",
                author_email=author.get("email", "") if isinstance(author, dict) else "",
                has_skills=(plugin_dir / "skills").is_dir(),
                has_commands=(plugin_dir / "commands").is_dir(),
                has_hooks=(plugin_dir / "hooks").is_dir(),
                has_agents=(plugin_dir / "agents").is_dir(),
                has_mcp=(plugin_dir / ".mcp.json").exists(),
            )
        except Exception as e:
            logger.warning(f"Failed to parse plugin {plugin_dir.name}: {e}")
            return None

    def scan_all(self) -> list[PluginInfo]:
        """Сканирует все плагины из всех маркетплейсов."""
        plugins: list[PluginInfo] = []

        if not self._plugins_dir.exists():
            logger.warning(f"Plugins directory not found: {self._plugins_dir}")
            return plugins

        # Перебираем маркетплейсы
        for marketplace_dir in self._plugins_dir.iterdir():
            if not marketplace_dir.is_dir():
                continue

            plugins_subdir = marketplace_dir / "plugins"
            if not plugins_subdir.exists():
                continue

            # Перебираем плагины
            for plugin_dir in plugins_subdir.iterdir():
                if not plugin_dir.is_dir():
                    continue

                plugin_info = self._scan_plugin(plugin_dir)
                if plugin_info:
                    plugins.append(plugin_info)

        return plugins

    def search(self, query: str, limit: int = 10) -> list[PluginInfo]:
        """Ищет плагины по запросу."""
        query_lower = query.lower()
        all_plugins = self.scan_all()

        # Фильтруем и сортируем по релевантности
        results: list[tuple[int, PluginInfo]] = []

        for plugin in all_plugins:
            score = 0

            # Точное совпадение имени
            if plugin.name.lower() == query_lower:
                score = 100
            # Имя содержит запрос
            elif query_lower in plugin.name.lower():
                score = 50
            # Описание содержит запрос
            elif query_lower in plugin.description.lower():
                score = 25

            if score > 0:
                results.append((score, plugin))

        # Сортируем по релевантности
        results.sort(key=lambda x: x[0], reverse=True)

        return [p for _, p in results[:limit]]

    def get_plugin(self, name: str) -> PluginInfo | None:
        """Получает плагин по имени."""
        all_plugins = self.scan_all()

        for plugin in all_plugins:
            if plugin.name == name:
                return plugin

        return None
