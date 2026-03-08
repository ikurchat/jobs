---
name: email-monitor
description: >
  Use this skill when user asks to "проверь почту", "что на почте", "новые письма",
  "check email", "check inbox", "входящие", "есть письма?", "что пришло",
  "проанализируй письмо", "разбери письмо",
  "создай задачу из письма", "в задачи", "в task-control",
  "что от руководителя", "письма от ...", "покажи письмо",
  "архивируй", "пропустить", "на контроле",
  "статистика почты", "email stats", "обучение почты".
  Triggers (monitoring): "мониторинг почты", "email monitor", "новые входящие".
  Triggers (feedback): "запомни", "всегда так делай", "этот отправитель важный".
  Triggers (learning): "статистика обучения", "профиль отправителя", "как реагировать".
tools:
  - Read
  - Bash
  - Write
  - mcp__jobs__tg_send_message
  - mcp__jobs__memory_search
  - mcp__jobs__memory_append
---

# Email Monitor

Мониторинг рабочей почты Gmail (адрес в env `GMAIL_EMAIL`), анализ содержимого, классификация по приоритету, предложение задач, подготовка ответов. Обучается на решениях owner'а.

## When NOT to Activate

- Если owner спрашивает про почту hey-store или другого аккаунта
- Если речь о Telegram-сообщениях, а не email
- Если нужна работа с документами без контекста почты → doc-review
- Если нужно управление задачами без контекста почты → task-control

## Environment

```
GMAIL_EMAIL=<your-email@gmail.com>
GMAIL_APP_PASSWORD=<app password>
DOCX_DECRYPT_PASSWORD=<decrypt password for encrypted .docx>
```

## Database

Feedback и профили хранятся в SQLite: `/data/email_learning.db`
Таблицы: `sender_profiles`, `email_feedback`, `stop_words` — создаются автоматически.

## Work Directory

`/dev/shm/email-monitor` — временные файлы (JSON дампы писем)

## State Tracking

```
mode: FETCH | CLASSIFY | DETAIL | CREATE_TASK | FEEDBACK | STATS
current_emails: [list of classified emails]
selected_email: {uid, subject, sender}
pending_action: OwnerAction
feedback_queue: [{sender, decision}]
```

## Mode Detection Table

| Триггер | Mode |
|---------|------|
| "проверь почту", "новые письма", "входящие" | FETCH |
| "что от VIPа", "покажи важные" | FETCH → фильтр |
| "покажи письмо", "подробнее", "открой" | DETAIL |
| "в задачи", "создай задачу" | CREATE_TASK |
| "архивируй", "пропустить", "на контроле" | FEEDBACK |
| "запомни", "всегда так", "этот важный" | FEEDBACK (explicit learning) |
| "статистика", "обучение", "профиль" | STATS |
| "трудозатраты", "effort", "нагрузка по почте" | EFFORT |
| "отчёт по почте", "email report", "почта в отчёт" | REPORT_DATA |

**ВАЖНО**: Gmail используется ИСКЛЮЧИТЕЛЬНО для чтения. Отправка писем НЕ поддерживается.

---

## Algorithm

### FETCH — Получение и классификация писем

1. Запустить Gmail-клиент:
```bash
cd /workspace/.claude/skills/email-monitor && PYTHONPATH=. python3 -m services.gmail_client fetch --unseen --since 3 --limit 20
```

2. Сохранить результат в `/dev/shm/email-monitor/inbox.json`

3. Загрузить feedback-историю из БД:
```bash
cd /workspace/.claude/skills/email-monitor && PYTHONPATH=. python3 -m services.feedback history --limit 200
```

4. Классифицировать батчем:
```bash
cd /workspace/.claude/skills/email-monitor && PYTHONPATH=. python3 -m services.classifier batch --emails /dev/shm/email-monitor/inbox.json --feedback /dev/shm/email-monitor/feedback.json
```

5. Сформировать сводку для owner'а:

**Формат сводки:**
```
📨 Входящие: N новых

🔴 Критичные (X):
  1. [VIP] Тема письма — 💡 Создать задачу
  2. ...

🟠 Важные (Y):
  1. [Отправитель] Тема — 💡 Рекомендация
  ...

🟡 Обычные (Z): список тем
🟢 Низкий приоритет (W): кратко
```

6. Отправить сводку owner'у. Спросить: "Показать подробности по какому-нибудь? Или выполнить рекомендации?"

### DETAIL — Подробности по письму

1. Получить полное письмо:
```bash
cd /workspace/.claude/skills/email-monitor && PYTHONPATH=. python3 -m services.gmail_client get <uid>
```

2. Обогатить парсером:
```bash
cd /workspace/.claude/skills/email-monitor && PYTHONPATH=. python3 -m services.parser summary --email /dev/shm/email-monitor/email_<uid>.json
```

3. Показать owner'у:
- Полный текст (или первые 2000 символов)
- Извлечённые сроки, ФИО, ссылки на документы
- Потенциальные задачи
- Рекомендуемое действие

4. Спросить: "Что делаем? [Задача / Ответ / Делегировать / На контроле / Архив / Пропустить]"

### CREATE_TASK — Создание задачи из письма (интеграция с task-control)

1. Извлечь из письма:
   - Суть задачи (title)
   - Срок (deadline), если указан
   - Ответственный (assignee_hint), если упомянут
   - Тип задачи (task_type): delegate / boss_control / regulatory / personal

2. **Маппинг приоритетов email → task-control:**
   - email CRITICAL (9-10) → task priority: critical
   - email HIGH (7-8) → task priority: high
   - email MEDIUM (4-6) → task priority: normal
   - email LOW (1-3) → task priority: low
   - email SPAM → НЕ создавать задачу

3. **Маппинг control_loop:**
   - VIP / руководство → up (boss_control)
   - Задача с assignee_hint → down (delegate)
   - Инцидент ИБ → down (delegate)
   - Регуляторное (ФСТЭК, ФСБ, 187-ФЗ) → regulatory
   - Иначе → internal (personal)

4. **Формат задачи для task-control:**
```json
{
  "title": "краткое описание",
  "task_type": "delegate|boss_control|regulatory|personal",
  "assignee_hint": "ФИО или null",
  "deadline": "YYYY-MM-DD или null",
  "priority": "critical|high|normal|low",
  "description": "контекст из письма",
  "control_loop": "up|down|regulatory|internal",
  "source_email_uid": "<uid>"
}
```

5. Предложить owner'у черновик задачи в формате выше
6. После подтверждения — создать задачу через task-control (используя доступный метод БД).
7. Пометить письмо: status=task_created, task_id=<id>
8. Записать feedback: отправитель → действие "create_task"

### FEEDBACK — Обратная связь и обучение

**При любом решении owner'а** по письму:

1. Записать feedback:
```bash
cd /workspace/.claude/skills/email-monitor && PYTHONPATH=. python3 -m services.feedback record --sender <email> --sender-name "<name>" --action <owner_action> --priority <priority> --category <category>
```

2. Если owner явно говорит "запомни" / "всегда так" / "этот важный":
   - Записать с повышенной confidence (0.8+)
   - Подтвердить: "Запомнил: письма от X — приоритет Y, действие Z"

3. **Правило обучения**: после 3 одинаковых решений по одному отправителю →
   confidence ≥ 0.7 → классификатор начинает автоматически предлагать это действие

### CORRECTION — Коррекция пропущенного

Если owner говорит "ты пропустил важное", "это было важно", "почему не показал":

```bash
cd /workspace/.claude/skills/email-monitor && PYTHONPATH=. python3 -m services.feedback correct --sender <email> --priority <correct_priority> --note "описание"
```

Коррекция = **двойной вес** (confidence += increment × 2). Профиль отправителя обновляется сразу.

### STOP_WORDS — Фильтрация нежелательных тем

Если owner говорит "не показывай письма про X", "X неинтересно":

```bash
cd /workspace/.claude/skills/email-monitor && PYTHONPATH=. python3 -m services.feedback stop_word --add "<слово>"
```

При FETCH — проверять subject и body_preview на стоп-слова. Если совпадение → НЕ включать в сводку.

Посмотреть текущие стоп-слова:
```bash
cd /workspace/.claude/skills/email-monitor && PYTHONPATH=. python3 -m services.feedback stop_word --list
```

### STATS — Статистика обучения

```bash
cd /workspace/.claude/skills/email-monitor && PYTHONPATH=. python3 -m services.feedback stats
```

Показать:
- Сколько отправителей изучено
- Распределение действий
- Топ уверенных профилей
- Средняя confidence

### EFFORT — Трудозатраты по почте

При обработке каждого письма (FEEDBACK) — оценивать effort_minutes и effort_category.

**Оценка трудозатрат (автоматическая):**
- СЭД рассмотрение: 15 мин
- СЭД исполнение (поручение с дедлайном): 60 мин
- Инцидент: 30 мин
- Подготовка отчёта/справки: 120 мин
- Совещание (подготовка): 30 мин
- Деловая переписка: 10 мин
- Прочее: 5 мин

Owner может скорректировать: "на это ушло 2 часа" → обновить effort_minutes.

Получить статистику:
```bash
cd /workspace/.claude/skills/email-monitor && PYTHONPATH=. python3 -m services.analytics effort --period weekly
```

### REPORT_DATA — Данные для отчёта

Формирует готовый блок "Работа с электронной почтой" для включения в недельный/месячный отчёт task-control.

```bash
cd /workspace/.claude/skills/email-monitor && PYTHONPATH=. python3 -m services.analytics report_data --period weekly
```

Возвращает:
- Общую статистику (писем, категории, приоритеты)
- Трудозатраты (часы по типам работ)
- СЭД-статистику (документы, авторы резолюций, риск просрочки)
- Готовый текст для вставки в отчёт

**Интеграция с task-control REPORT_GEN:**
Когда task-control генерирует недельный отчёт — добавить секцию из email-monitor report_data.

---

## VIP Rules [CRITICAL]

### VIP-руководитель (имя в rules/custom_rules.json)
- **ВСЁ от VIP = максимальный приоритет (10/10)**
- СЭД от него: если есть слова "контроль", "срок", "исполнение" → critical
- СЭД от него без контрольных слов → high (не spam, не игнорировать!)
- Всегда предлагать: CREATE_TASK
- Всегда уведомлять owner'а немедленно

---

## Security Rules

- Gmail = ТОЛЬКО чтение, отправка НЕ поддерживается
- App password хранится ТОЛЬКО в env var, НИКОГДА в файлах/логах
- Вложения: скачивать в /dev/shm/, удалять после обработки
- PII: не сохранять полные тексты писем в Baserow (только метаданные + preview)
- Feedback: хранить sender_email, action, priority в SQLite — НЕ тело письма

## Communication Format

- Язык: русский (если owner не пишет на EN)
- Сводка: компактная, с emoji-приоритетами
- Длинные письма: показывать preview + "Показать полностью?"
- Сообщения > 4000 символов: разбивать на части

## Lessons Learned [CRITICAL]

### LL-1: YouGile = письма от YouGile
"Проверка YouGile" означает проверку писем ОТ YouGile в Gmail. НЕ логиниться в YouGile. Фильтровать по отправителю (notification@yougile.com или аналог).

### LL-2: Молотова — всегда обращать внимание
Письма от Молотовой А.В. всегда важные и по делу. Автоматически поднимать приоритет.

### LL-3: Не пропускать письма руководства
Все письма от руководителей (Модестов и другие VIP) ОБЯЗАТЕЛЬНО выносить в сводку. Owner ловил случаи, когда бот пропускал задачу от Модестова — это критическая ошибка.

### LL-4: БПЛА — стоп-тема
Письма связанные с БПЛА не показывать (стоп-слово).

## Integration Points

- **task-control**: создание задач из писем + секция "Работа с почтой" в отчётах
- **task-control REPORT_GEN**: при генерации отчёта — вызвать `services.analytics report_data`
- **doc-review**: если письмо содержит .docx → предложить рецензию
- **schedule-meeting**: если письмо о встрече → предложить создать
- **SQLite**: `/data/email_learning.db` — sender_profiles, email_feedback, stop_words

## Cleanup

После обработки сессии:
```bash
rm -rf /dev/shm/email-monitor/*
```

Не удалять rules/custom_rules.json и config.json — они постоянные.
