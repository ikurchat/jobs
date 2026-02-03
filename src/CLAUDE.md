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
get_session(telegram_id: int, user_display_name: str | None = None) → UserSession
get_owner_session() → UserSession
reset_session(telegram_id: int)
reset_all()  # После изменения MCP конфига
```

### UsersRepository (users/repository.py)
```python
upsert_user(...)
find_user(query)  # Fuzzy search
create_task(...)
get_overdue_tasks()
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
