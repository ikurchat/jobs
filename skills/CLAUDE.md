# Skills System

Skills — расширения функциональности Jobs через Claude Agent SDK.

## Архитектура

**Skills работают нативно через SDK:**

```python
ClaudeAgentOptions(
    setting_sources=["project"],  # Включает filesystem-based configuration
    allowed_tools=["Skill", ...],
)
```

SDK автоматически:
1. Ищет skills в `{cwd}/.claude/skills/`
2. Загружает metadata (frontmatter) в контекст
3. Активирует skill по semantic match с description
4. Инжектит SKILL.md body при активации

## Структура Skill

```
.claude/skills/                    # В Docker: /workspace/.claude/skills/
├── schedule-meeting/
│   └── SKILL.md                   # Обязательно
└── another-skill/
    └── SKILL.md
```

### SKILL.md формат

```markdown
---
name: skill-name
description: Use this skill when user asks to "phrase 1", "phrase 2".
             Include exact trigger phrases for semantic matching.
tools: Read, Glob, Grep, Bash
---

# Skill Title

## Algorithm

1. Step 1
2. Step 2

## User Session Instructions

(Опционально) Инструкции для user session при ConversationTask.
```

**Ключевые поля frontmatter:**

| Поле | Описание |
|------|----------|
| `name` | Имя skill |
| `description` | Trigger phrases для semantic matching (ВАЖНО!) |
| `tools` | Разрешённые tools |

## Как SDK активирует Skills

```
User: "Договорись о встрече с @masha завтра"
         │
         ▼
SDK читает все skills metadata (frontmatter)
         │
         ▼
Semantic match: "договорись о встрече" ↔ skill description
         │
         ▼
Найден skill: schedule-meeting
         │
         ▼
SDK инжектит SKILL.md body в контекст
         │
         ▼
Claude выполняет алгоритм из SKILL.md
```

## Docker Volume Mount

Skills монтируются из хоста:

```yaml
# docker-compose.yml
volumes:
  - ./skills:/workspace/.claude/skills:ro
```

## Создание нового Skill

1. Создай `skills/my-skill/SKILL.md`

2. Добавь frontmatter с description:
```yaml
---
name: my-skill
description: Use when user asks to "do something", "another phrase".
tools: Read, Bash
---
```

3. Напиши алгоритм

4. Skill автоматически подхватится (hot-reload)

## Cross-Session Communication

Skills могут использовать ConversationTask для делегирования:

```python
# В SKILL.md алгоритме:
start_conversation(
    user="@masha",
    task_type="meeting",
    context={"slots": "12:00-20:00"},
    initial_message="..."
)
```

User session получит контекст через `format_conversation_context()` и сможет:
- Видеть задачу в system prompt
- Собрать информацию
- Обновить результат через `update_conversation()`

## Best Practices

1. **Description = trigger phrases**. SDK матчит семантически по description.

2. **Конкретные фразы**. "Use when user asks to X" лучше чем "Handles X".

3. **tools = минимум**. Указывай только нужные tools.

4. **Тестируй matching**. Проверь что skill активируется на ожидаемые фразы.
