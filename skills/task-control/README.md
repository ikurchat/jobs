# task-control skill v1.0

AI-ассистент руководителя подразделения ИБ — делегирование, контроль исполнения, сменный режим, планирование, отчётность.

## Архитектура

```
SKILL.md (оркестратор)
  ├── config.json                 # Настройки таблиц, расписания, пороги
  ├── config/settings.py          # Загрузка конфига, env vars, JSON output
  ├── config/prompts.py           # Промпты для Claude (роль, парсинг, стиль)
  ├── models/enums.py             # TaskType, Status, Priority, ...
  ├── models/task.py              # Dataclass модели (Employee, Task, PlanItem, ...)
  ├── services/baserow.py         # Baserow REST client (CRUD, batch, CLI)
  ├── services/parser.py          # Валидация, обогащение, дедупликация задач
  ├── services/correlator.py      # Сопоставление задач ↔ пунктов плана
  ├── services/scheduler.py       # Генерация текстов брифинга, пушей, отчётов
  ├── services/shift_manager.py   # График смен, нагрузка, передача
  ├── services/reporter.py        # Генерация .docx (планы, отчёты)
  ├── services/analytics.py       # Метрики, аномалии, дисциплина
  ├── handlers/message.py         # Форматирование сообщений
  └── handlers/callbacks.py       # Парсинг ответов owner'а
```

Claude (через SKILL.md) — интеллектуальный слой: NL парсинг, классификация, семантическая корреляция.
Python скрипты — инструменты данных: CRUD в Baserow, .docx генерация, вычисления.

## Настройка

### 1. Переменные окружения

```env
BASEROW_URL=https://your-baserow.example.com
BASEROW_TOKEN=your-api-token
```

### 2. Создание таблиц в Baserow

Создайте 8 таблиц в Baserow согласно схеме в ТЗ (раздел 8):
- employees, shift_schedule, tasks, plan_items
- regulatory_tracks, task_log, skill_updates, settings

### 3. Заполнение config.json

Пропишите ID созданных таблиц:
```json
{
  "baserow": {
    "tables": {
      "employees": 101,
      "shift_schedule": 102,
      "tasks": 103,
      ...
    }
  }
}
```

## Использование (CLI)

```bash
cd /workspace/.claude/skills/task-control && PYTHONPATH=. python3 -m services.baserow list <table_id>
cd /workspace/.claude/skills/task-control && PYTHONPATH=. python3 -m services.shift_manager who_on_shift --date 2025-02-10 --shifts shifts.json
cd /workspace/.claude/skills/task-control && PYTHONPATH=. python3 -m services.scheduler briefing --date 2025-02-10 --tasks t.json --shifts s.json
cd /workspace/.claude/skills/task-control && PYTHONPATH=. python3 -m services.reporter weekly_plan --input plan.json --output plan.docx
```

## Тестирование

```bash
cd /root/jobs/skills/task-control && PYTHONPATH=. python3 -m pytest tests/ -v
```

## Три контура контроля

1. **Вниз** (подчинённые): delegate, collab, inform
2. **Вверх** (руководство): boss_control, report_up
3. **Регуляторный**: regulatory

## Рабочий график owner'а

| День | Время | Пуш-окно |
|------|-------|----------|
| Пн–Чт | 09:00–18:00 | 17:00–18:00 |
| Пт | 09:00–16:20 | 15:00–16:20 |
| Сб–Вс | Выходной | — |
