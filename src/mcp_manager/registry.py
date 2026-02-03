"""
MCP Registry — поиск серверов в официальном реестре.
"""

from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger

from src.config import settings


REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0.1"


@dataclass
class MCPPackage:
    """Информация о пакете MCP сервера."""
    registry_type: str  # npm, pip, etc.
    name: str
    version: str | None = None


@dataclass
class MCPServerInfo:
    """Информация о MCP сервере из реестра."""
    name: str
    title: str
    description: str
    version: str
    packages: list[MCPPackage]
    repository: str | None = None

    @property
    def install_command(self) -> str | None:
        """Команда для установки."""
        for pkg in self.packages:
            if pkg.registry_type == "npm":
                return f"npx {pkg.name}"
            elif pkg.registry_type == "pip":
                return f"uvx {pkg.name}"
        return None


class MCPRegistry:
    """Клиент для MCP Registry API."""

    def __init__(self) -> None:
        self._base_url = REGISTRY_URL

    async def search(self, query: str, limit: int = 10) -> list[MCPServerInfo]:
        """
        Ищет MCP серверы по запросу.

        Args:
            query: Поисковый запрос
            limit: Максимум результатов

        Returns:
            Список найденных серверов
        """
        try:
            async with httpx.AsyncClient(proxy=settings.http_proxy) as client:
                response = await client.get(
                    f"{self._base_url}/servers",
                    params={
                        "search": query,
                        "limit": limit,
                        "version": "latest",
                    },
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()

            servers = []
            for item in data.get("servers", []):
                packages = []
                for pkg in item.get("packages", []):
                    packages.append(MCPPackage(
                        registry_type=pkg.get("registryType", "unknown"),
                        name=pkg.get("name", ""),
                        version=pkg.get("version"),
                    ))

                servers.append(MCPServerInfo(
                    name=item.get("name", ""),
                    title=item.get("title", item.get("name", "")),
                    description=item.get("description", ""),
                    version=item.get("version", "latest"),
                    packages=packages,
                    repository=item.get("repository"),
                ))

            logger.info(f"Found {len(servers)} MCP servers for '{query}'")
            return servers

        except Exception as e:
            logger.error(f"MCP Registry search error: {e}")
            return []

    async def get_server(self, name: str) -> MCPServerInfo | None:
        """
        Получает информацию о конкретном сервере.

        Args:
            name: Имя сервера

        Returns:
            Информация о сервере или None
        """
        try:
            async with httpx.AsyncClient(proxy=settings.http_proxy) as client:
                response = await client.get(
                    f"{self._base_url}/servers/{name}/versions/latest",
                    timeout=30,
                )
                response.raise_for_status()
                item = response.json()

            packages = []
            for pkg in item.get("packages", []):
                packages.append(MCPPackage(
                    registry_type=pkg.get("registryType", "unknown"),
                    name=pkg.get("name", ""),
                    version=pkg.get("version"),
                ))

            return MCPServerInfo(
                name=item.get("name", name),
                title=item.get("title", name),
                description=item.get("description", ""),
                version=item.get("version", "latest"),
                packages=packages,
                repository=item.get("repository"),
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            logger.error(f"MCP Registry get error: {e}")
            return None
        except Exception as e:
            logger.error(f"MCP Registry get error: {e}")
            return None
