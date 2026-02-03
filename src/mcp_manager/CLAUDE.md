# mcp_manager/ — Управление внешними MCP серверами

## Структура

```
mcp_manager/
├── __init__.py     # Экспорты
├── registry.py     # Поиск в MCP Registry (700+ серверов)
├── config.py       # Хранение конфига серверов
└── tools.py        # MCP инструменты для управления
```

## Концепция

Пользователь может через чат:
1. Искать MCP серверы в официальном реестре
2. Устанавливать их (добавлять в конфиг)
3. Настраивать credentials (DATABASE_URL, API keys)
4. Включать/отключать/удалять

## MCPRegistry (registry.py)

### API
- Base URL: `https://registry.modelcontextprotocol.io/v0.1`
- Endpoints: `/servers`, `/servers/{name}`

### MCPServerInfo
```python
@dataclass
class MCPServerInfo:
    name: str           # "postgres", "github"
    title: str          # "PostgreSQL MCP Server"
    description: str
    version: str
    packages: list[MCPPackage]  # npm/pip пакеты
    repository: str | None

    @property
    def install_command(self) -> str:
        # npx для npm, uvx для pip
```

### Методы
```python
registry = MCPRegistry()
results = await registry.search("postgres")  # Поиск
info = await registry.get_server("postgres") # Детали
```

## MCPConfig (config.py)

### MCPServerConfig
```python
@dataclass
class MCPServerConfig:
    name: str
    command: str          # "npx", "uvx", etc.
    args: list[str]       # ["-y", "@modelcontextprotocol/server-postgres"]
    env: dict[str, str]   # {"DATABASE_URL": "postgresql://..."}
    enabled: bool = True
    title: str = ""
    description: str = ""
    source: str = "manual"  # или "registry"
```

### MCPConfig
```python
class MCPConfig:
    add_server(...)
    remove_server(name)
    enable_server(name)
    disable_server(name)
    set_env(name, key, value)
    get_enabled_servers()
    to_mcp_json()  # Формат для Claude SDK
    list_servers() # Для отображения
```

### Хранение
- Файл: `/data/mcp_servers.json`
- Автоматическое сохранение через `save_mcp_config()`

## MCP Tools (tools.py)

| Tool | Описание | После вызова |
|------|----------|--------------|
| `mcp_search(query)` | Поиск в реестре | — |
| `mcp_install(name, command, args)` | Добавить сервер | reset session |
| `mcp_set_env(name, key, value)` | Установить credential | reset session |
| `mcp_list()` | Список установленных | — |
| `mcp_enable(name)` | Включить | reset session |
| `mcp_disable(name)` | Отключить | reset session |
| `mcp_remove(name)` | Удалить | reset session |

### Важно: Session Reset

После любого изменения конфига вызывается:
```python
get_session_manager().reset_all()
```

Это сбрасывает все Claude сессии, чтобы при следующем сообщении
загрузился новый конфиг MCP серверов.

## Пример использования

```
User: подключи postgres

Agent: [mcp_search query="postgres"]
🔍 Найдено:
1. postgres — PostgreSQL MCP Server (npx)
2. ...

User: установи первый

Agent: [mcp_install name="postgres" command="npx" args=["-y", "@modelcontextprotocol/server-postgres"]]
✅ Сервер postgres установлен
⚠️ Нужно указать DATABASE_URL

User: postgresql://user:pass@localhost/mydb

Agent: [mcp_set_env name="postgres" key="DATABASE_URL" value="postgresql://..."]
✅ Credentials установлены
🔄 Сессия перезапущена

User: покажи таблицы

Agent: [использует postgres MCP сервер]
📋 Tables: users, orders, ...
```

## Singletons

```python
get_mcp_config() → MCPConfig    # Глобальный конфиг
save_mcp_config()               # Сохранить изменения
```
