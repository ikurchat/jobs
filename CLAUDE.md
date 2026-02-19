# Jobs — Personal AI Assistant

Автономный ИИ-ассистент на базе Claude SDK в Telegram. Мульти-сессионная архитектура с изоляцией по ролям.

## Архитектура

- **Owner Session** — `bypassPermissions`, полный доступ (Memory, Scheduler, MCP, Browser, Telegram API)
- **External Sessions** — `default` permissions, только: `get_my_tasks`, `send_summary_to_owner`, `update_task`
- **Task Sessions** — persistent per-task, resume через `session_id` в БД
- **TriggerManager** — scheduler, heartbeat, tg_channel → TriggerExecutor → owner session
- **SQLite** — `external_users`, `tasks` (+ `next_step`, `session_id`), `trigger_subscriptions`

## Ключевые модули

| Путь | Описание |
|------|----------|
| `src/users/` | SessionManager, Repository, Tools, Prompts |
| `src/telegram/` | Telethon handlers + Telegram API tools |
| `src/memory/` | MEMORY.md + vector search (70% vector + 30% BM25) |
| `src/tools/` | Scheduler + разделение по ролям |
| `src/triggers/` | Unified trigger system |
| `src/mcp_manager/` | Внешние MCP серверы |
| `src/plugin_manager/` | Плагины из маркетплейса |
| `src/skill_manager/` | Управление локальными skills |
| `skills/` | Skills через SDK (монтируется в `.claude/skills/`) |
| `browser/` | Docker-контейнер с Chromium (Playwright MCP, noVNC) |

## Browser

Персистентный Chromium через Playwright MCP. Workflow: `browser_navigate` → `browser_snapshot` (ref-ы) → взаимодействие по ref. HAProxy проксирует CDP. Подробнее в tool descriptions.

## Skills (SDK native)

`setting_sources=["project"]` → SDK ищет `{cwd}/.claude/skills/*/SKILL.md`, матчит семантически по `description`. Cross-session через `ConversationTask`. Подробнее: `skills/CLAUDE.md`.

## Plugins

Пакеты с skills, commands, hooks, agents и MCP серверами. Управление: `plugin_search`, `plugin_install`, `plugin_list`, `plugin_enable/disable`, `plugin_remove`.

## Triggers

Все события → `TriggerExecutor.execute(TriggerEvent)`. Встроенные: `scheduler`, `heartbeat`. Динамические: `tg_channel`. Подписки в SQLite.

## Telegram команды

| Команда | Доступ | Описание |
|---------|--------|----------|
| `/help` | все | Список команд |
| `/stop` | owner | Прервать текущий запрос |
| `/clear` | все | Сбросить сессию |
| `/usage` | owner | Лимиты API |
| `/update` | owner | Обновить бота |

## Task Sessions

Задачи со `skill` получают persistent session. Follow-up обрабатывается в том же контексте. Heartbeat resume'ит все task sessions параллельно. `next_step` — текущий шаг для heartbeat.

## Git workflow

Squash merge в main. Формат: `type: описание` (feat, fix, refactor, security, docs).

## Запуск

`docker-compose up` — два сервиса: `jobs` (бот) + `browser` (Chromium + noVNC).

## Singletons

`get_session_manager()`, `get_users_repository()`, `get_storage()`, `get_index()`, `get_mcp_config()`, `get_plugin_config()`, `get_trigger_manager()`

---

## Skill Audit & Optimization

При получении команды `audit skills` — пройди по всем `skills/*/SKILL.md` и для каждого проверь:
1. Есть ли frontmatter (name, description) с точными trigger-словами
2. Алгоритм пошаговый и однозначный (нет "можно так или так")
3. Есть негативные примеры (когда НЕ активировать)
4. Все правила из MEMORY.md, относящиеся к скиллу, включены в SKILL.md
5. Нет противоречий между SKILL.md и MEMORY.md
6. Конкретные значения указаны числами, не словами

Выведи краткий отчёт: ok / замечание / критично — для каждого скилла.

При `sync memory` — найди правила в MEMORY.md → SKILL.md. Покажи что куда перенести.
