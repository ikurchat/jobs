# Jobs — Personal AI Assistant

## Обзор

Автономный ИИ-ассистент на базе Claude SDK в Telegram.
Мульти-сессионная архитектура с изоляцией по ролям.

## Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                    Docker Container                              │
│                                                                  │
│  ┌─────────────────────┐                                        │
│  │   Owner Session     │ ← Полный доступ                        │
│  │   bypassPermissions │   Memory, Scheduler, MCP, Bash...      │
│  └─────────────────────┘                                        │
│                                                                  │
│  ┌─────────────────────┐                                        │
│  │   External Sessions │ ← Ограниченный доступ                  │
│  │   default perms     │   Только: get_my_tasks,                │
│  └─────────────────────┘   send_summary_to_owner, update_task   │
│                                                                  │
│            ↓                                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              SQLite (db.sqlite)                          │   │
│  │  • external_users  • user_tasks  • scheduled_tasks       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  /data/sessions/  — Claude session IDs                          │
│  /workspace/      — рабочая директория owner'а                  │
└─────────────────────────────────────────────────────────────────┘
```

## Ключевые модули

| Путь | Описание |
|------|----------|
| `src/users/` | SessionManager, Repository, Tools, Prompts |
| `src/telegram/` | Telethon handlers |
| `src/memory/` | MEMORY.md + vector search |
| `src/tools/` | Scheduler + разделение по ролям |
| `src/mcp_manager/` | Внешние MCP серверы |

## Разделение доступа

| Tool | Owner | External |
|------|-------|----------|
| Bash, Read, Write | ✅ | ❌ |
| Memory | ✅ | ❌ |
| Scheduler | ✅ | ❌ |
| MCP Manager | ✅ | ❌ |
| send_to_user | ✅ | ❌ |
| create_user_task | ✅ | ❌ |
| send_summary_to_owner | ❌ | ✅ |
| get_my_tasks | ❌ | ✅ |

## Переменные окружения

```env
TG_API_ID, TG_API_HASH  — Telegram API
TG_USER_ID              — ID владельца (owner)
ANTHROPIC_API_KEY       — Claude API (опционально, есть OAuth)
OPENAI_API_KEY          — Whisper транскрипция
HTTP_PROXY              — Прокси для API
HEARTBEAT_INTERVAL_MINUTES — Проверки (0 = выкл)
```

## Singletons

```python
get_session_manager()   # Мульти-сессии
get_users_repository()  # Пользователи и задачи
get_storage()           # Файловая память
get_index()             # Векторный поиск
get_mcp_config()        # MCP серверы
```

## Запуск

```bash
docker-compose up
```

## Хранение

```
/data/
├── db.sqlite           # SQLite БД
├── sessions/           # Claude session IDs
│   ├── {owner_id}.session
│   └── {user_id}.session
├── telethon.session    # Telegram сессия
└── mcp_servers.json    # MCP конфиг

/workspace/
├── MEMORY.md           # Долгосрочная память
├── memory/             # Дневные логи
└── uploads/            # Файлы от пользователей
```
