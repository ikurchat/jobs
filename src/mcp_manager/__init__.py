"""
MCP Manager — управление сторонними MCP серверами.

Позволяет:
- Искать MCP серверы в реестре
- Подключать/отключать серверы
- Управлять credentials
"""

from src.mcp_manager.registry import MCPRegistry
from src.mcp_manager.config import MCPConfig, get_mcp_config
from src.mcp_manager.tools import MCP_MANAGER_TOOLS, MCP_MANAGER_TOOL_NAMES

__all__ = [
    "MCPRegistry",
    "MCPConfig",
    "get_mcp_config",
    "MCP_MANAGER_TOOLS",
    "MCP_MANAGER_TOOL_NAMES",
]
