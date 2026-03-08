---
name: sed-monitor
description: >
  Use when user asks about СЭД, документы СЭД, "проверь СЭД", "что нового в СЭД",
  "найди документ", "документ номер", "резолюции", "мои резолюции",
  "статус СЭД", "синхронизация СЭД", "обнови пароль СЭД",
  "что мне расписали", "непросмотренные документы", "поиск в СЭД",
  "скачай документ", "пришли документ", "дай PDF",
  link contains "doc.rscc.ru", link contains "sd-praktika.ru".
tools: Read, Bash, Grep, Glob
---

# СЭД Практика Monitor

Мониторинг корпоративной СЭД (doc.rscc.ru). Только чтение — никаких управляющих воздействий.
Работаем нежно: рандомные задержки, минимум запросов, не отсвечиваем.

## CLI — как вызывать

Все команды через cli.py (рабочая директория: `/workspace/.claude/skills/sed-monitor/`):

```bash
SED_DIR=/workspace/.claude/skills/sed-monitor
python3 $SED_DIR/cli.py <command> [args]
```

| Команда | Описание |
|---------|----------|
| `python3 $SED_DIR/cli.py status` | Статус: connectivity + DB stats + last sync |
| `python3 $SED_DIR/cli.py connectivity` | Проверить связь с proxy/SED/auth |
| `python3 $SED_DIR/cli.py sync` | Полная синхронизация всех папок |
| `python3 $SED_DIR/cli.py document <doc_id>` | Полная инфо по документу (fetch если нет в БД) |
| `python3 $SED_DIR/cli.py search <query>` | Поиск по номеру/тексту в СЭД |
| `python3 $SED_DIR/cli.py resolutions [assignee]` | Мои резолюции (default: Панков) |
| `python3 $SED_DIR/cli.py unviewed` | Непросмотренные документы |
| `python3 $SED_DIR/cli.py download <doc_id>` | Скачать документ как PDF |
| `python3 $SED_DIR/cli.py text <doc_id>` | OCR-текст документа |
| `python3 $SED_DIR/cli.py stats` | Статистика БД |

Все команды выводят JSON (кроме text и download).

## Парсинг ссылок

Из ссылок извлекай `id` и передавай в `document`:
- `https://doc.rscc.ru:444/web/document/view?id=883493` → `python3 $SED_DIR/cli.py document 883493`
- `https://app.sd-praktika.ru/?id=875962` → `python3 $SED_DIR/cli.py document 875962`

## Обновление пароля

**Trigger:** "обнови пароль СЭД"

```bash
python3 -c "
import sys; sys.path.insert(0, '/workspace/.claude/skills/sed-monitor')
from config.settings import save_auth
save_auth(login='Панков И.Ю.', user_id='81081', group_id='33364', password='NEW_PASSWORD')
print('OK')
"
```

1. Спроси пароль у owner'а
2. Подставь в команду выше
3. Проверь: `python3 $SED_DIR/cli.py connectivity`

## Формат ответа

При выдаче информации о документе показывай:
- Номер, дата регистрации, краткое содержание
- Резолюции: кто → кому, текст, дедлайн, статус
- OCR-текст (первые 500 символов, если есть)

При резолюциях группируй по статусу, выделяй просроченные.

## Data Model

| Table | Purpose |
|-------|---------|
| documents | Метаданные документа (номер, дата, содержание, папка) |
| resolutions | Кто кому что расписал (автор, исполнитель, текст, дедлайн) |
| document_cards | Полная карточка (JSON) |
| pages | OCR-текст по страницам |
| sync_log | История синхронизаций |

## Security

- Пароль: `/data/sed_auth.json` (0600)
- Сертификат: `/data/sed/cert.pem` + `key.pem` (ГОСТ, до 2027-03-06)
- Трафик через sed-proxy sidecar
- Только чтение, без управляющих воздействий
- Рандомные задержки между запросами
