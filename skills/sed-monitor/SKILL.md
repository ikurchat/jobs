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

## Architecture

```
jobs container ──HTTP──▶ sed-proxy ──GOST TLS──▶ doc.rscc.ru:444
                         (sidecar)                (СЭД Практика)
```

- `sed-proxy`: sidecar container с GOST OpenSSL, принимает plain HTTP, шлёт GOST TLS
- Аутентификация: DNSID + auth_token cookies, клиентский ГОСТ-сертификат
- Данные: SQLite (`/data/sed_monitor.db`)

## 1. STATUS — Статус системы

**Trigger:** "статус СЭД", "СЭД работает?"

```python
from services.monitor import check_status
status = check_status()
# Показать: connectivity (proxy/sed/auth), stats, last_sync
```

## 2. SYNC — Синхронизация

**Trigger:** "проверь СЭД", "что нового в СЭД", "синхронизация"

```python
from services.monitor import run_sync
result = run_sync(sync_type="manual")
# Показать: new_documents, new_resolutions, errors
```

## 3. MY_RESOLUTIONS — Мои резолюции

**Trigger:** "что мне расписали", "мои резолюции", "мои документы"

```python
from services.monitor import get_my_summary
summary = get_my_summary("Панков")
# Показать: resolutions с deadline, unviewed docs, stats
```

Format response:
- Group by status (active/completed)
- Show deadline, author, document number
- Highlight overdue items

## 4. SEARCH — Поиск документа

**Trigger:** "найди документ N", "документ номер X", link to doc.rscc.ru

```python
# By number or keyword:
from services.monitor import search_and_fetch
docs = search_and_fetch("123-456")

# By doc_id (from link):
from services.monitor import sync_single_document
result = sync_single_document(doc_id)
```

Parse links:
- `https://doc.rscc.ru:444/web/document/view?id=883493` → doc_id=883493
- `https://app.sd-praktika.ru/?id=875962` → doc_id=875962
- Extract `id` query parameter from any of these domains

## 5. DOCUMENT — Детали документа

**Trigger:** "покажи документ", "карточка документа", "текст документа"

```python
from services.monitor import get_document_summary
info = get_document_summary(doc_id)
# info: document, resolutions, card, text (OCR), full_text_length
```

Show:
- Number, date, short content
- Resolutions (who → whom, text, deadline, status)
- Card fields if available
- First 500 chars of OCR text

## 6. PASSWORD — Обновление пароля

**Trigger:** "обнови пароль СЭД", "новый пароль СЭД"

```python
from config.settings import save_auth
save_auth(login="Панков И.Ю.", user_id="81081", group_id="33364", password="NEW_PASSWORD")
```

1. Ask owner for new password
2. Save via `save_auth()` (file permissions 0600)
3. Force re-authenticate: `sed_client.authenticate(force=True)`
4. Report success/failure

## 7. DOWNLOAD — Скачать документ как PDF

**Trigger:** "скачай документ", "пришли документ", "дай PDF"

```python
from services.monitor import download_document
pdf_path = download_document(doc_id)
# pdf_path → отправить через send_to_user как файл
```

Скачивает страницы-сканы (JPEG) через sed-proxy и склеивает в PDF (Pillow или img2pdf).
Отправить owner'у через Telegram.

## 8. UNVIEWED — Непросмотренные

**Trigger:** "непросмотренные", "новые документы"

```python
from services.db import get_unviewed_documents
docs = get_unviewed_documents()
```

## Data Model

| Table | Purpose |
|-------|---------|
| documents | Document metadata (number, date, content, folder, viewed) |
| resolutions | Who assigned what to whom (author, assignee, text, deadline) |
| document_cards | Full card JSON |
| pages | OCR text per page |
| sync_log | Sync history |

## Security Notes

- Password stored in `/data/sed_auth.json` with 0600 permissions
- Client certificate: `/data/sed/cert.pem` + `key.pem` (GOST, valid until 2027-03-06)
- All traffic via sed-proxy sidecar (no direct GOST TLS from jobs container)
- Read-only operations only — no document modifications
- Random delays between requests (0.3-1.5s) to avoid detection
