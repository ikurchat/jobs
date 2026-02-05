# src/ — Исходный код Jobs

## Структура

```
src/
├── main.py           # Entry point
├── config.py         # Settings (pydantic)
├── heartbeat.py      # Проактивные проверки
├── media.py          # Whisper, сохранение файлов
├── setup.py          # Первоначальная настройка
│
├── users/            # Мульти-сессии, пользователи, задачи, промпты
├── telegram/         # Telethon клиент и handlers
├── memory/           # MEMORY.md + vector search
├── tools/            # Scheduler + разделение по ролям
└── mcp_manager/      # Внешние MCP серверы
```

## Поток данных

```
Telegram message
    ↓
handlers._on_message()
    ↓
set_current_user(user_id)     # contextvars для async-safe
    ↓
session_manager.get_session(user_id, display_name)
    ↓
    ├── Owner? → OWNER_ALLOWED_TOOLS + bypassPermissions
    └── External? → EXTERNAL_ALLOWED_TOOLS + default permissions
    ↓
session.query_stream(prompt)
    ↓
Response → Telegram
```

## Ключевые классы

### SessionManager (users/session_manager.py)
```python
get_session(telegram_id, user_display_name) → UserSession
get_owner_session() → UserSession
create_task_session(task_id) → UserSession         # Persistent session для задачи
get_task_session(task_id, session_id) → UserSession | None  # Восстановление из БД
reset_session(telegram_id)
reset_all()
```

### UsersRepository (users/repository.py)
```python
upsert_user(...)
find_user(query)  # Fuzzy search
create_task(...)
update_task(task_id, status, result, next_step)
update_task_session(task_id, session_id)  # Persistent task session ID
list_tasks(assignee_id, status, kind, overdue_only, include_done)
```

### Settings (config.py)
```python
tg_api_id, tg_api_hash, tg_user_id  # Telegram
anthropic_api_key, http_proxy       # Claude
sessions_dir                        # /data/sessions/
```

## Разделение tools по ролям

```python
# tools/__init__.py

OWNER_ALLOWED_TOOLS = [
    Scheduler, Memory, MCP Manager, User Management
]

EXTERNAL_ALLOWED_TOOLS = [
    send_summary_to_owner, get_my_tasks, update_task_status
]
```

## Task model (users/models.py)

```python
@dataclass
class Task:
    id, title, status, kind, context, result
    assignee_id, created_by, deadline
    schedule_at, schedule_repeat       # Для kind="scheduled"
    next_step: str | None              # Текущий шаг (heartbeat)
    session_id: str | None             # Claude SDK session ID (persistent)
```

## Промпты

Все в `users/prompts.py`:
- `OWNER_SYSTEM_PROMPT`
- `EXTERNAL_USER_PROMPT_TEMPLATE`
- `HEARTBEAT_PROMPT`

## Singletons

```python
get_session_manager()   # users/session_manager.py
get_users_repository()  # users/repository.py
get_storage()           # memory/storage.py
get_index()             # memory/index.py
get_mcp_config()        # mcp_manager/config.py
```

## Безопасность

| Аспект | Owner | External |
|--------|-------|----------|
| permission_mode | bypassPermissions | default |
| allowed_tools | Все | Только user tools |
| workspace доступ | Полный | Нет |
| MCP серверы | Все | Нет |
