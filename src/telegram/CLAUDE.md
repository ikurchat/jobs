# telegram/ — Telegram интеграция

## Файлы

| Файл | Описание |
|------|----------|
| `client.py` | Создание Telethon клиента, сохранение сессии |
| `auth.py` | Интерактивная авторизация (телефон → код → 2FA) |
| `handlers.py` | Обработка входящих сообщений (мульти-сессии) |

## TelegramHandlers (handlers.py)

### Мульти-сессионная архитектура

```python
# Принимаем сообщения от ВСЕХ пользователей
events.NewMessage(incoming=True)

# Каждый пользователь → своя Claude сессия
session_manager = get_session_manager()
session = session_manager.get_session(user_id, user_display_name)
```

### Роли пользователей

| Роль | Доступ | Tools |
|------|--------|-------|
| **Owner** (tg_user_id) | Полный | Owner + Memory + Scheduler + MCP |
| **External** | Ограниченный | External user tools |

### Поддерживаемые типы сообщений
- **Текст** → напрямую в Claude
- **Голосовое** → Whisper транскрипция → Claude
- **Фото** → сохранение в `/workspace/uploads/photos/`
- **Документы** → сохранение в `/workspace/uploads/documents/`

### Процесс обработки

```python
async def _on_message(event):
    user_id = event.sender_id
    is_owner = user_id == settings.tg_user_id

    # 1. Для external users — upsert в БД
    if not is_owner:
        await repo.upsert_user(user_id, username, ...)

    # 2. Устанавливаем контекст для tools
    set_current_user(user_id)

    # 3. Получаем сессию для пользователя
    session = session_manager.get_session(user_id, display_name)

    # 4. Стримим ответ
    async for text, tool_name, is_final in session.query_stream(prompt):
        if tool_name:
            await status_msg.edit(f"🔧 {tool_name}...")

    # 5. Отправить результат
    # (Telegraph если > 4000 символов)
```

### Форматирование инструментов

```python
icons = {
    "Read": "📖 Читаю",
    "Write": "✍️ Пишу",
    "Bash": "💻 Выполняю",
    # Scheduler
    "schedule_task": "📅 Планирую",
    # User tools
    "send_to_user": "📤 Отправляю",
    "create_user_task": "📝 Создаю задачу",
    "send_summary_to_owner": "📨 Сводка",
    ...
}
```

### Telegram Sender

```python
# Устанавливается при инициализации handlers
set_telegram_sender(self._send_message)

# Используется user tools для отправки сообщений
async def _send_message(user_id: int, text: str) -> None:
    await self._client.send_message(user_id, text)
```

## Авторизация (auth.py)

```python
async def interactive_auth(client):
    # 1. Проверить: уже авторизован?
    # 2. Ввод номера телефона
    # 3. Получить код в Telegram
    # 4. Ввести код (+ 2FA если есть)
    # 5. Сохранить session string
```

## Клиент (client.py)

```python
def create_client(session=None):
    # Device Model для маскировки под реальный телефон
    return TelegramClient(
        session,
        api_id=settings.tg_api_id,
        api_hash=settings.tg_api_hash,
        device_model="Samsung SM-G998B",
        system_version="Android 13",
        app_version="10.0.0",
    )
```

## Сценарии

### Owner отправляет сообщение
1. Получаем owner session (полный доступ)
2. Выполняем запрос с owner tools
3. Отправляем ответ

### External user отправляет сообщение
1. Создаём/обновляем запись в БД
2. Получаем external session (ограниченный доступ)
3. Claude выясняет детали
4. При необходимости — `send_summary_to_owner()`

### Owner поручает задачу
1. Owner: "поручи Маше отчёт к пятнице"
2. Claude использует `resolve_user("Маша")`
3. Claude использует `create_user_task(...)`
4. Маша получает уведомление через `send_to_user()`
