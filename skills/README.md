# Jobs Skills

Skills через нативную поддержку Claude Agent SDK.

## Как это работает

SDK автоматически:
1. Ищет skills в `/workspace/.claude/skills/` (монтируется из `./skills/`)
2. Загружает frontmatter (metadata) в контекст
3. Активирует по semantic match с `description`
4. Инжектит SKILL.md body при активации

```python
# session_manager.py
ClaudeAgentOptions(
    setting_sources=["project"],  # Включает skills
    allowed_tools=["Skill", ...],
)
```

## Структура

```
skills/                            # На хосте
├── CLAUDE.md                      # Документация
├── README.md                      # Этот файл
└── schedule-meeting/
    └── SKILL.md                   # С frontmatter
```

В Docker монтируется как `/workspace/.claude/skills/`.

## Доступные Skills

| Skill | Triggers | Описание |
|-------|----------|----------|
| schedule-meeting | "договорись о встрече", "назначь встречу" | Согласование встречи через cross-session |

## Создание Skill

1. Создай `skills/my-skill/SKILL.md`

2. Добавь frontmatter:
```yaml
---
name: my-skill
description: Use when user asks to "trigger phrase 1", "trigger phrase 2".
tools: Read, Bash
---
```

3. Напиши алгоритм

4. Skill автоматически подхватится

## Документация

- [CLAUDE.md](./CLAUDE.md) — полная документация
- [Claude Agent SDK Skills](https://platform.claude.com/docs/en/agent-sdk/skills)
