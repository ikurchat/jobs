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
| `src/plugin_manager/` | Плагины из маркетплейса |
| `src/skill_manager/` | Управление локальными skills |
| `skills/` | Skills через SDK (монтируется в `.claude/skills/`) |

## Skills (нативная поддержка SDK)

Skills работают через `setting_sources=["project"]` в ClaudeAgentOptions.

```
skills/                           # На хосте
└── schedule-meeting/
    └── SKILL.md                  # С YAML frontmatter
        │
        ▼ docker-compose mount
        │
/workspace/.claude/skills/        # В контейнере
└── schedule-meeting/
    └── SKILL.md
```

**SDK автоматически:**
1. Ищет skills в `{cwd}/.claude/skills/`
2. Загружает frontmatter (metadata) в контекст
3. Semantic match: user request ↔ `description`
4. Инжектит SKILL.md body при активации

**SKILL.md формат:**
```yaml
---
name: schedule-meeting
description: Use when user asks to "договорись о встрече", "назначь встречу"...
tools: Read, Bash
---

# Algorithm
1. resolve_user()
2. start_conversation()
...
```

**Cross-session:** Skills могут использовать `ConversationTask` для делегирования задач другим пользователям.

**Управление через чат:**
```
— Создай skill для парсинга hh.ru
— skill_create name="hh-parser" description="..." algorithm="..."

— Покажи все skills
— skill_list
```

**Tools:**
| Tool | Описание |
|------|----------|
| `skill_create` | Создать новый skill |
| `skill_list` | Список локальных skills |
| `skill_show` | Показать содержимое |
| `skill_edit` | Редактировать skill |
| `skill_delete` | Удалить skill |

Документация: `skills/CLAUDE.md`

## Plugins (маркетплейс)

Плагины — пакеты с skills, commands, hooks, agents и MCP серверами.

**Управление через чат:**
```
— Найди плагины для code review
— plugin_search query="code review"

— Установи code-review
— plugin_install name="code-review"
```

**Tools:**
| Tool | Описание |
|------|----------|
| `plugin_search` | Поиск по маркетплейсу |
| `plugin_install` | Установка плагина |
| `plugin_list` | Список установленных |
| `plugin_available` | Все доступные плагины |
| `plugin_enable/disable` | Вкл/выкл без удаления |
| `plugin_remove` | Полное удаление |

**Хранение:**
- Маркетплейс: `/data/.claude/plugins/marketplaces/`
- Конфиг: `/data/plugins.json`

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
get_plugin_config()     # Плагины
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
├── mcp_servers.json    # MCP конфиг
└── plugins.json        # Установленные плагины

/workspace/
├── MEMORY.md           # Долгосрочная память
├── memory/             # Дневные логи
└── uploads/            # Файлы от пользователей
```
