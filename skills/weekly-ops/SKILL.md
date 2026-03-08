---
name: weekly-ops
context: fork
description: >
  Use this skill when the user wants to create or fill a weekly plan, weekly report,
  monthly plan, monthly report. Triggers: "план на неделю", "еженедельный план",
  "отчёт за неделю", "заполни отчёт", "месячный отчёт", "план на месяц",
  "отчёт за месяц", "агрегируй отчёты", "заполни план", "plan", "report",
  "weekly plan", "weekly report", "monthly plan", "monthly report",
  "сформируй план", "сформируй отчёт", "план на следующую неделю",
  "отчёт за прошлую неделю", "черновик отчёта", "черновик плана",
  "подготовь черновик", "draft report", "draft plan", "auto draft",
  "настрой автодрафт", "вопросы по плану"
tools:
  - Bash
  - Read
  - Write
  - Glob
  - mcp__jobs__tg_send_message
  - mcp__jobs__tg_send_media
  - mcp__jobs__tg_download_media
  - mcp__jobs__memory_search
  - mcp__jobs__memory_log
---

# weekly-ops — Планы и отчёты

Единая точка для еженедельных/ежемесячных планов и отчётов. Подтягивает данные из БД (локальный SQLite), предзаполняет формулировки из памяти, согласовывает блоками, генерит .docx.

## Определение режима

| Условие | Режим |
|---------|-------|
| "план на неделю", "сформируй план", "plan" | PLAN_WEEKLY |
| "план на месяц", "ежемесячный план" | PLAN_MONTHLY |
| "отчёт за неделю", "заполни отчёт", "report" | REPORT_WEEKLY |
| "отчёт за месяц", "месячный отчёт" | REPORT_MONTHLY |
| "черновик отчёта", "draft report" | AUTO_DRAFT_REPORT |
| "черновик плана", "draft plan" | AUTO_DRAFT_PLAN |
| "вопросы по плану", "что уточнить" | QUESTIONS |
| .docx прикреплён + контекст плана/отчёта | TEMPLATE_FILL |

## State Tracking

Поддерживай в контексте:

```
mode: PLAN_WEEKLY | PLAN_MONTHLY | REPORT_WEEKLY | REPORT_MONTHLY | TEMPLATE_FILL
period_start: YYYY-MM-DD
period_end: YYYY-MM-DD
doc_type: plan | report
items: [...]
preview_cursor: 0
blocks_total: N
approved_blocks: [...]
pending_edits: {...}
status: detecting | loading | building | previewing | generating | sending | published
work_dir: /dev/shm/weekly-ops/session_xxxxx
```

---

## Бизнес-правила [CRITICAL]

Эти правила применяются ВСЕГДА, без исключений:

### LL-3: Не дублировать допы с плановыми
Перед добавлением задачи в «Дополнительные мероприятия» проверь overlap ≥ 60% значимых слов с плановыми пунктами. Если совпадает — НЕ добавлять.

### LL-8: В планах НЕТ процентов
Никаких "50%", "80% готовности" в тексте пунктов плана. Проценты допустимы ТОЛЬКО в отметках отчёта.

### LL-9: В планах НЕТ ФИО подрядчиков
Заменять ФИО подрядчиков на подразделение «СИТ» или название организации. Исключение: штатные сотрудники.

### LL-10: Проверить ВСЕ активные задачи
Обязательно pull всех задач со статусами in_progress/assigned/waiting_input. Нельзя пропустить активную задачу.

### Обязательные пункты
В каждом еженедельном плане ВСЕГДА включать пункты из `mandatory_items` в config.json (Молотова А.В., мониторинг ИБ, стажёр Ворожбит).

### Исключить ЦОК
Пункты, связанные с ЦОК (Центр обеспечения кибербезопасности), НЕ включать.

### Только внутренние мероприятия
В планы/отчёты НЕ включать: доработки кода бота, настройки скиллов, техническую работу над ботом, AI assistant.

---

## Дедлайны

- Еженедельные план/отчёт: до пятницы текущей недели
- Ежемесячные план/отчёт: до **20-го числа** месяца
- Если 20-е — выходной: допустимо 21-22, но ТОЛЬКО с отдельного ОК owner'а
- При приближении дедлайна (17-18 числа) → напомнить: "Месячный отчёт нужен до 20-го"

---

## 1. PLAN_WEEKLY

**1.1.** Определи период:
- Если сегодня пн-чт → текущая неделя (пн-пт)
- Если сегодня пт-вс → следующая неделя (пн-пт)
- Owner может указать конкретные даты

**1.2.** Создай рабочую директорию:
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -c "
from config.settings import load_config, create_work_dir
cfg = load_config()
wd = create_work_dir(cfg)
print(wd)
"
```

**1.3.** Загрузи данные из БД:
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -m services.data_loader pull --period-start YYYY-MM-DD --period-end YYYY-MM-DD
```

**1.4.** Сохрани результат в `{work_dir}/raw.json`.

**1.5.** Построй план:
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -m services.plan_builder build --data {work_dir}/raw.json --output {work_dir}/plan.json
```

**1.6.** Прочитай `{work_dir}/plan.json` и проверь:
- Обязательные пункты есть (Молотова, мониторинг, стажёр)?
- ЦОК отсутствует?
- Нет процентов?
- Нет ФИО подрядчиков?
- Все active задачи включены?

**1.7.** Сформируй preview блоками по 5 пунктов:
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -m services.preview_formatter plan --data {work_dir}/plan.json --period "План на DD.MM-DD.MM"
```

**1.8.** Отправь первый блок owner'у через `mcp__jobs__tg_send_message`.

**1.9.** Цикл согласования:
- "ок" / "да" → approve блок, отправить следующий
- "всё ок" → approve все оставшиеся блоки
- "② сроки до пятницы" → правка, повторить блок
- "⑤ убрать" → удалить пункт
- "добавь: Совещание по ИБ | 20.02 | Петров" → добавить пункт
- Применить правки, пересчитать нумерацию, показать обновлённый блок

**1.10.** После согласования всех блоков → сгенерировать .docx:
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -m services.docx_generator plan --data {work_dir}/plan_final.json --output {work_dir}/plan.docx
```

**1.11.** Отправить .docx owner'у через `mcp__jobs__tg_send_media`.

**1.12.** Сохранить plan_items и версию плана в БД:
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -c "
from services.db import save_plan_items, save_plan_version
import json
with open('{work_dir}/plan_final.json') as f:
    items = json.load(f)
save_plan_items(items, 'YYYY-MM-DD', 'YYYY-MM-DD', 'weekly')
v = save_plan_version('YYYY-MM-DD', 'YYYY-MM-DD', 'weekly', items, 'approved', '{work_dir}/plan.docx')
print(f'Saved {len(items)} items, version {v}')
"
```

**1.13.** Если owner просит — опубликовать в Pi Space.

**1.14.** Очистить рабочую директорию:
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -c "
from config.settings import cleanup_work_dir
from pathlib import Path
cleanup_work_dir(Path('{work_dir}'))
"
```

---

## 2. PLAN_MONTHLY

Аналогично PLAN_WEEKLY, но:
- Период = весь месяц (1-е — последний день)
- Нет разбиения на "плановые/дополнительные" — одна таблица
- Дедлайн: до 20-го числа
- Если 20-е выходной → запросить ОК owner'а на 21-22

---

## 3. REPORT_WEEKLY

**3.1.** Определи период (аналогично плану).

**3.2.** Создай рабочую директорию.

**3.3.** Загрузи данные:
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -m services.data_loader pull --period-start YYYY-MM-DD --period-end YYYY-MM-DD
```

**3.4.** Загрузи формулировочную память:
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -m services.formulation_memory get_all_as_dict
```

**3.5.** Построй отчёт:
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -m services.report_builder build --data {work_dir}/raw.json --memory {work_dir}/memory.json --output {work_dir}/report.json
```

**3.6.** Прочитай report.json, проверь warnings.

**3.7.** Сформируй preview блоками (с отметками):
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -m services.preview_formatter report --data {work_dir}/report_items.json --period "Отчёт за DD.MM-DD.MM"
```

**3.8.** Отправь блок owner'у.

**3.9.** Цикл согласования (аналогично плану, но с отметками):
- "ок" → approve блок
- "② 80%, акт подписан" → правка отметки
- "всё ок" → approve все

**3.10.** После approve — СОХРАНИТЬ утверждённые формулировки и версию отчёта в БД:
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -c "
import json
from services.db import bulk_save_formulations, save_report_version
with open('{work_dir}/approved_items.json') as f:
    items = json.load(f)
saved = bulk_save_formulations(items)
v = save_report_version('YYYY-MM-DD', 'YYYY-MM-DD', 'weekly', items, 'approved', '{work_dir}/report.docx')
print(f'Saved {saved} formulations, report version {v}')
"
```

**3.11.** Генерация .docx — два пути:

**a) Есть шаблон (owner прислал .docx или скачан из Pi Space):**
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -m services.docx_generator fill --template {work_dir}/template.docx --data {work_dir}/report_final.json --output {work_dir}/report.docx
```

**b) Нет шаблона — генерация с нуля:**
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -m services.docx_generator report --data {work_dir}/report_final.json --output {work_dir}/report.docx
```

**3.12.** Обновить plan_items.completion_note в БД.

**3.13.** Отправить + опубликовать + очистка.

---

## 4. REPORT_MONTHLY

**4.1.** Определи месяц.

**4.2.** Агрегируй все недельные plan_items за месяц:
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -m services.monthly_aggregator aggregate --month YYYY-MM --output {work_dir}/monthly.json
```

**4.3.** Дедупликация: одинаковые пункты из разных недель → одна строка с последней отметкой.

**4.4.** Допы — в конец таблицы (без разбиения "плановые/доп").

**4.5.** Стандартный flow: preview → approve → .docx → send.

---

## 5. TEMPLATE_FILL

Когда owner присылает .docx шаблон:

**5.1.** Скачай файл через `mcp__jobs__tg_download_media` → `{work_dir}/template.docx`.

**5.2.** Определи период из документа (из заголовка или спроси owner'а).

**5.3.** Загрузи данные и построй отчёт (шаги 3.3-3.5).

**5.4.** Заполни шаблон:
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -m services.docx_generator fill --template {work_dir}/template.docx --data {work_dir}/report.json --output {work_dir}/filled.docx
```

**5.5.** Валидация:
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -m services.docx_generator validate --doc {work_dir}/filled.docx
```

**5.6.** При ошибках — исправить и показать owner'у.

**5.7.** Отправить через `mcp__jobs__tg_send_media`.

---

## UX: Формат preview

### План (без «Отметки»):
```
📋 План на 17.02-21.02 | Блок 1/4:

① Мониторинг событий ИБ | В течение недели | Управление ИБ
② Согласование Порядка мониторинга ИБ (Молотова А.В.) | В течение недели | Управление ИБ
③ Справка по ГосСОПКА | до 19.02 | Сидоров А.В.
④ Контроль SOC | В течение недели | Управление ИБ
⑤ Проверка дедлайнов ФСТЭК | до 21.02 | Петров Д.А.

✅ Подтвердить | ✏️ Правки | ➕ Добавить
```

### Отчёт (с «Отметкой»):
```
📊 Отчёт за 17.02-21.02 | Блок 1/4:

① Мониторинг событий ИБ
   → Выполнено. Обработано 312 событий, 2 инцидента.
② Согласование Порядка мониторинга ИБ (Молотова)
   → В работе (60%). Промежуточный акт направлен.
③ Справка по ГосСОПКА
   → Выполнено. Справка утверждена (рег. №42-ИБ).

✅ Подтвердить | ✏️ Правки (например: ② 80%, акт подписан)
```

### Парсинг ответов:
- "ок" / "да" → approve текущий блок, отправить следующий
- "② сроки до пятницы" → правка пункта ②, повторить блок
- "⑤ убрать" → удалить пункт ⑤
- "добавь: Совещание по ИБ | 20.02 | Петров" → добавить пункт
- "всё ок" → approve все оставшиеся блоки разом

---

## Форматирование .docx

| Параметр | Значение |
|----------|----------|
| Ориентация | Landscape (29.7 × 21 cm) |
| Поля | L=3.0, R=1.0, T=2.0, B=2.0 cm |
| Шрифт таблицы | **12pt TNR** |
| Шрифт заголовка | 14pt TNR |
| Колонки | № п/п (6%) · Мероприятия (38%) · Сроки (16%) · Ответственный (20%) · Отметка (20%) |
| Bold | Только строка заголовка таблицы |
| Недельный | 2 секции: "Планируемые мероприятия" (merged) → задачи → "Дополнительные" (merged) → допы |
| Месячный | 1 таблица без разбиения, допы в конце |

---

## Формулировочная память

Хранится в SQLite (`/data/weekly_ops.db`, таблица `formulation_memory`).

После **explicit approve** блока owner'ом — сохранить утверждённые формулировки через `db.bulk_save_formulations()`.

При построении следующего отчёта — сначала искать в памяти по keyword overlap (≥ 60%) через `db.search_formulation()`.
Если найдено — подставить паттерн + заполнить переменные из задач.
Если нет — сгенерировать автоматически из task.status + task.result.

---

## Версионирование и обратная связь

### Хранение версий
Каждый план и отчёт сохраняется как версия в SQLite:
- `plan_versions` — draft → approved → final (с путём к .docx)
- `report_versions` — draft → approved → final

При получении плана/отчёта — ВСЕГДА сохранять версию через `db.save_plan_version()` / `db.save_report_version()`.

### Обратная связь owner'а
КАЖДУЮ правку owner'а логировать через `db.log_feedback()`:

| Действие owner'а | action | Что записать |
|---|---|---|
| "② сроки до пятницы" | `edit` | old_text=старый текст, new_text=новый |
| "⑤ убрать" | `delete` | old_text=удалённый пункт |
| "добавь: ..." | `add` | new_text=добавленный пункт |
| "ок" / "да" | `approve_block` | item_number=номер блока |
| "всё ок" | `approve_all` | — |

```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -c "
from services.db import log_feedback
log_feedback('YYYY-MM-DD', 'YYYY-MM-DD', 'plan', 'edit', item_number=2, old_text='...', new_text='...')
"
```

### Использование обратной связи
При построении СЛЕДУЮЩЕГО плана/отчёта:
1. Загрузить feedback за предыдущие периоды через `db.get_feedback_stats()`
2. Если owner часто удаляет определённые типы пунктов — не предлагать их
3. Если owner часто правит формулировки — использовать утверждённые из `formulation_memory`

### Получение предыдущего плана
Бот ВСЕГДА может найти предыдущий план:
```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -c "
from services.db import get_latest_plan_version
v = get_latest_plan_version('YYYY-MM-DD', 'YYYY-MM-DD')
if v: print(f'Version {v[\"version\"]}, status={v[\"status\"]}, items={len(v[\"items\"])}')
else: print('No plan found')
"
```

---

## 6. AUTO_DRAFT — Автоматическая подготовка черновиков

### 6.1. Авто-черновик отчёта (пятница)

Бот может автоматически подготовить черновик отчёта на основе утверждённого плана.

**Когда запускать:**
- Пятница утро (по расписанию через `schedule_task`)
- Или по запросу owner'а: "подготовь черновик отчёта", "draft report"

**Алгоритм:**
1. Загрузить план текущей недели из БД
2. Для каждого пункта — поискать в формулировочной памяти
3. Пункты без ясного статуса → пометить `[Требуется уточнение]`
4. Сформировать вопросы по неясным пунктам
5. Сохранить черновик как draft-версию отчёта
6. Отправить owner'у вопросы + preview черновика

```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -m services.auto_draft report --period-start YYYY-MM-DD --period-end YYYY-MM-DD
```

**Результат:** JSON с полями `items`, `questions`, `version`, `needs_input`.

### 6.2. Авто-черновик плана (после отчёта / понедельник)

Бот может автоматически подготовить черновик плана на следующую неделю.

**Когда запускать:**
- После утверждения отчёта за текущую неделю
- Или понедельник утро (по расписанию)
- Или по запросу: "подготовь черновик плана", "draft plan"

**Алгоритм:**
1. Загрузить отчёт за прошлую неделю → определить невыполненные пункты
2. Carry-over незавершённых пунктов
3. Добавить обязательные пункты (mandatory_items)
4. Проверить активные задачи (in_progress) — добавить если нет в плане
5. Учесть feedback: если owner часто удаляет определённые пункты — не предлагать
6. Сохранить черновик как draft-версию плана

```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -m services.auto_draft plan --period-start YYYY-MM-DD --period-end YYYY-MM-DD
```

**Результат:** JSON с полями `items`, `version`, `carried_over`, `mandatory`.

### 6.3. Интеграция auto-draft в основной flow

При вызове PLAN_WEEKLY или REPORT_WEEKLY:

1. **Сначала** проверить — есть ли уже draft-версия в БД?
2. Если есть → загрузить и использовать как основу (не строить с нуля)
3. Если нет → построить стандартным способом (шаги 1.3-1.5 / 3.3-3.5)

```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -c "
from services.db import get_latest_plan_version
v = get_latest_plan_version('YYYY-MM-DD', 'YYYY-MM-DD')
if v and v['status'] == 'draft':
    print(f'Draft v{v[\"version\"]} found, {len(v[\"items\"])} items')
else:
    print('No draft, build from scratch')
"
```

---

## 7. QUESTIONS — Модуль уточняющих вопросов

### 7.1. Назначение

Перед финализацией отчёта бот анализирует пункты плана и задаёт конкретные вопросы owner'у по тем пунктам, где статус неясен. Это повышает качество черновика отчёта.

### 7.2. Генерация вопросов

```bash
cd /workspace/.claude/skills/weekly-ops && PYTHONPATH=. python3 -m services.auto_draft questions --period-start YYYY-MM-DD --period-end YYYY-MM-DD --format message
```

**Типы вопросов (определяются автоматически по ключевым словам):**

| Тип пункта | Вопрос |
|------------|--------|
| мониторинг, контроль | Сколько событий/инцидентов? Ключевые выводы? |
| согласование, утверждение | Документ согласован/подписан? На каком этапе? |
| разработка, подготовка | Готово? Если в работе — какой процент? |
| проверка, аудит | Проверка завершена? Какие результаты? |
| совещание, встреча | Состоялось? Ключевые решения? |
| общий | Выполнено / в работе / перенесено? |

### 7.3. Формат вопросов owner'у

```
📋 Для подготовки отчёта уточни по следующим пунктам:

❓ п.1: «Мониторинг событий ИБ» — сколько событий/инцидентов? Ключевые выводы?
❓ п.3: «Согласование Порядка мониторинга ИБ» — документ согласован/подписан? На каком этапе?
❓ п.5: «Подготовка справки по ГосСОПКА» — готово? Если в работе — какой процент?

Отвечай в формате: «п.2 — выполнено, акт подписан»
```

### 7.4. Парсинг ответов на вопросы

Owner отвечает в свободной форме:
- "п.1 — 312 событий, 2 инцидента" → обновить completion_note пункта 1
- "п.3 — в работе 60%, промежуточный акт направлен" → обновить пункт 3
- "п.5 — выполнено, справка утверждена рег.42-ИБ" → обновить пункт 5, статус=done

После получения ответов — обновить черновик отчёта и показать preview.

### 7.5. Flow: вопросы → черновик → согласование

```
Пятница утро:
  1. auto_draft report → черновик + вопросы
  2. Отправить вопросы owner'у
  3. Owner отвечает
  4. Обновить черновик по ответам
  5. Показать preview блоками → стандартный цикл согласования
  6. После approve → docx → отправить
```

---

## 8. Расписание (schedule_task)

Для автоматизации отчётно-плановой деятельности создать scheduled tasks:

### Пятница 09:00 — черновик отчёта
```
schedule_task(
  title="Черновик отчёта за неделю",
  prompt="Подготовь черновик отчёта за текущую неделю. Используй /weekly-ops auto-draft report.",
  time="09:00",
  repeat="7d"
)
```

### Понедельник 09:00 — черновик плана
```
schedule_task(
  title="Черновик плана на неделю",
  prompt="Подготовь черновик плана на текущую неделю. Используй /weekly-ops auto-draft plan.",
  time="09:00",
  repeat="7d"
)
```

Бот НЕ создаёт расписание автоматически — только по запросу owner'а ("настрой автодрафт", "включи автоматику").

---

## Негативные примеры (когда НЕ активировать)

- "сводка" / "брифинг" / "что по задачам" → task-control (BRIEFING)
- "разбери задачи" / "парси" → task-control (PARSE_TASKS)
- "кто на смене" → task-control (SHIFT_QUERY)
- "статистика" / "дисциплина" → task-control (ANALYTICS)
- "ФСТЭК дедлайны" → task-control (REGULATORY)
- Справка (.docx с шапкой) → doc-review
