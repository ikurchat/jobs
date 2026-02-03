"""
Plugin Manager — управление плагинами Claude через чат.
"""

from src.plugin_manager.config import (
    PluginConfig,
    get_plugin_config,
    save_plugin_config,
)
from src.plugin_manager.registry import PluginRegistry, PluginInfo
from src.plugin_manager.tools import PLUGIN_MANAGER_TOOLS, PLUGIN_MANAGER_TOOL_NAMES

__all__ = [
    "PluginConfig",
    "get_plugin_config",
    "save_plugin_config",
    "PluginRegistry",
    "PluginInfo",
    "PLUGIN_MANAGER_TOOLS",
    "PLUGIN_MANAGER_TOOL_NAMES",
]
