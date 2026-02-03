# users/ — Мульти-сессии и управление пользователями

## Концепция

Каждый пользователь Telegram получает изолированную Claude сессию:
- **Owner** (tg_user_id) — полный доступ, все tools
- **External users** — ограниченный доступ, только user tools

## Структура

```
users/
├── __init__.py          # Экспорты
├── models.py            # ExternalUser, UserTask
├── repository.py        # SQLite + fuzzy search
├── session_manager.py   # Мульти-сессии по telegram_id
├── prompts.py           # Все system prompts
└── tools.py             # MCP tools (contextvars для user_id)
```

## Разделение доступа

| Возможность | Owner | External |
|-------------|-------|----------|
| Bash, Read, Write | ✅ | ❌ |
| Memory tools | ✅ | ❌ |
| Scheduler | ✅ | ❌ |
| MCP Manager | ✅ | ❌ |
| send_to_user | ✅ | ❌ |
| create_user_task | ✅ | ❌ |
| send_summary_to_owner | ❌ | ✅ |
| get_my_tasks | ❌ | ✅ |
| permission_mode | bypassPermissions | default |

## Models (models.py)

### ExternalUser
```python
@dataclass
class ExternalUser:
    telegram_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    phone: str | None
    notes: str
    first_contact: datetime
    last_contact: datetime
```

### UserTask
```python
@dataclass
class UserTask:
    id: str
    assignee_id: int
    description: str
    deadline: datetime | None
    status: Literal["pending", "accepted", "completed", "overdue"]
    created_at: datetime
    created_by: int | None
```

## Repository (repository.py)

### Fuzzy Search
```python
find_user(query) → ExternalUser | None
# Поиск по:
# 1. Точное совпадение @username
# 2. telegram_id (если число)
# 3. Частичное совпадение имени
# 4. Fuzzy matching через биграммы (порог 50%)
```

## SessionManager (session_manager.py)

### Thread-safe сессии
```python
session_manager = get_session_manager()
session = session_manager.get_session(telegram_id, display_name)

# Сессии кешируются в памяти
# session_id сохраняется в /data/sessions/{telegram_id}.session
```

### Разные опции по ролям
```python
# Owner
allowed_tools = OWNER_ALLOWED_TOOLS
permission_mode = "bypassPermissions"

# External
allowed_tools = EXTERNAL_ALLOWED_TOOLS
permission_mode = "default"
```

## Tools (tools.py)

### Contextvars (async-safe)
```python
from contextvars import ContextVar

_current_user_id_var: ContextVar[int | None] = ContextVar("current_user_id")

def set_current_user(telegram_id: int) -> None:
    _current_user_id_var.set(telegram_id)

def _get_current_user_id() -> int:
    return _current_user_id_var.get()
```

### Owner Tools
- `send_to_user(user, message)`
- `create_user_task(user, description, deadline)`
- `get_user_tasks(user)`
- `resolve_user(query)`
- `list_users()`
- `get_overdue_tasks()`

### External User Tools
- `send_summary_to_owner(summary)`
- `get_my_tasks()`
- `update_task_status(task_id, status)`

## Prompts (prompts.py)

| Промпт | Назначение |
|--------|------------|
| `OWNER_SYSTEM_PROMPT` | Полный доступ + user management |
| `EXTERNAL_USER_PROMPT_TEMPLATE` | Выяснить детали → сводка owner'у |
| `HEARTBEAT_PROMPT` | Периодическая проверка |

## Singletons

```python
get_session_manager() → SessionManager
get_users_repository() → UsersRepository
```

## БД Схема

```sql
CREATE TABLE external_users (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    phone TEXT,
    notes TEXT DEFAULT '',
    first_contact TEXT,
    last_contact TEXT
);

CREATE TABLE user_tasks (
    id TEXT PRIMARY KEY,
    assignee_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    deadline TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT,
    created_by INTEGER
);
```
