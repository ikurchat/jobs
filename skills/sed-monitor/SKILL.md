---
name: sed-monitor
description: >
  Use when user asks about СЭД, документы СЭД, "проверь СЭД",
  "найди документ", "документ номер", "резолюции",
  "статус СЭД", "обнови токен СЭД",
  "скачай документ", "пришли документ", "дай PDF",
  link contains "doc.rscc.ru", link contains "sd-praktika.ru".
tools: Read, Bash
---

# СЭД Практика

Корпоративная СЭД (doc.rscc.ru). Только чтение.

## Как вызывать

```
SED=/workspace/.claude/skills/sed-monitor/cli.py
```

### Ссылка на документ или ID → полный отчёт
```bash
python3 $SED doc https://app.sd-praktika.ru/?id=875962
python3 $SED doc 875962
```
Выводит: номер, дата, содержание, резолюции (кто→кому), карточка, OCR-текст (первые 500 символов).
Результат — готовый текст, пересылай owner'у как есть.

### Поиск по номеру или тексту
```bash
python3 $SED search "123-456"
```

### Скачать PDF (сканы)
```bash
python3 $SED pdf 875962
```
Вернёт путь к файлу — отправь owner'у через send_to_user.

### Проверить связь
```bash
python3 $SED check
```

### Установить токен авторизации
```bash
python3 $SED token <dnsid> <auth_token>
```
Токен живёт ~182 дня. Пароль НЕ хранится — только токен.

## Правила

- Получил ссылку с `sd-praktika.ru` или `doc.rscc.ru` → сразу `python3 $SED doc <ссылка>`
- Результат `doc` — готовый отчёт, отправляй owner'у без изменений
- PDF только по явному запросу ("скачай", "пришли файл")
- Не редактируй файлы скилла
