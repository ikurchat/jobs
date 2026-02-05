---
name: telegraph
description: Публикует длинный текст в Telegraph и отправляет ссылку. Используй когда ответ длиннее 3000 символов или содержит структурированный контент (статьи, обзоры, инструкции). Триггеры: "напиши в телеграф", "опубликуй в telegraph", а также автоматически при длинных ответах.
tools:
  - Bash
  - mcp__jobs__tg_send_message
---

# Telegraph

Публикует контент в Telegraph через API и отправляет ссылку пользователю.

## Когда использовать

- Ответ длиннее 3000 символов
- Структурированный контент: статьи, обзоры, инструкции, отчёты
- Пользователь явно просит опубликовать в Telegraph

## Алгоритм

### 1. Создай аккаунт (только первый раз)

```bash
curl -s "https://api.telegra.ph/createAccount?short_name=JobsBot&author_name=Jobs"
```

Сохрани `access_token` из ответа в memory (`memory_append`).

### 2. Если токен уже есть — загрузи из памяти

```bash
# memory_search("telegraph token")
```

### 3. Подготовь контент

Собери массив Node для Telegraph. Формат:

- `{"tag": "p", "children": ["текст"]}` — параграф
- `{"tag": "h3", "children": ["заголовок"]}` — подзаголовок
- `{"tag": "h4", "children": ["подзаголовок"]}` — подподзаголовок
- `{"tag": "b", "children": ["жирный"]}` — жирный текст
- `{"tag": "i", "children": ["курсив"]}` — курсив
- `{"tag": "a", "attrs": {"href": "url"}, "children": ["текст"]}` — ссылка
- `{"tag": "pre", "children": ["код"]}` — блок кода
- `{"tag": "code", "children": ["inline"]}` — inline код
- `{"tag": "blockquote", "children": ["цитата"]}` — цитата
- `{"tag": "ul", "children": [{"tag": "li", "children": ["пункт"]}]}` — список
- `{"tag": "br"}` — перенос строки

Вложенное форматирование: `{"tag": "p", "children": ["Текст ", {"tag": "b", "children": ["жирный"]}, " продолжение"]}`

### 4. Опубликуй

```bash
curl -s -X POST "https://api.telegra.ph/createPage" \
  -H "Content-Type: application/json" \
  -d '{
    "access_token": "<TOKEN>",
    "title": "<TITLE>",
    "author_name": "Jobs",
    "content": <JSON_CONTENT_ARRAY>
  }'
```

### 5. Отправь ссылку

Из ответа возьми `result.url` и отправь пользователю через `tg_send_message`.

## Важно

- Максимум 64 KB на страницу
- Title обязателен, макс 256 символов
- Если контент содержит спецсимволы в JSON — экранируй
- Токен сохраняй в memory, не создавай аккаунт каждый раз
