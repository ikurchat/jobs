---
name: osint
context: fork
disable-model-invocation: true
description: >
  Use this skill when the user asks to look up, investigate, or gather intelligence
  about a person, phone number, username, email, vehicle, address, domain, or photo.
  OSINT via paid Telegram bots: Cilordbot (Telegram OSINT — username, phone, groups,
  channels, messages) and Sherlock Report (comprehensive — phone, FIO, email, auto, social,
  documents, address, cadastre, OGRN, domain, face search by photo).
  Both sources are paid. Bot usernames change on blocks — the skill resolves them automatically.
  Triggers: "пробей", "пробить", "шерлок", "osint", "кто это", "проверь человека",
  "найди информацию", "пробив по номеру", "пробив по фио", "что за человек",
  "собери инфу", "разведка", "проверь по номеру", "пробей телегу", "sherlock",
  "check person", "lookup", "investigate", "reverse image search", "face lookup",
  "phone number lookup", "поиск по фото", "пробив по фото"
tools:
  - Bash
  - Read
  - Write
  - Glob
  - Grep
  - mcp__jobs__tg_send_message
  - mcp__jobs__tg_read_channel
  - mcp__jobs__tg_read_chat
  - mcp__jobs__tg_send_media
  - mcp__jobs__tg_download_media
  - mcp__jobs__tg_get_user_info
  - mcp__browser__browser_navigate
  - mcp__browser__browser_snapshot
  - mcp__browser__browser_click
---

# OSINT Sherlock — разведка через Telegram-ботов

Автоматический OSINT через два платных Telegram-бота: **Cilordbot** (telelog, Telegram-OSINT) и **Sherlock Report** (комплексный пробив). Username обоих ботов меняется при блокировках — скилл резолвит актуальных автоматически.

**Рабочая директория скилла:** `/workspace/.claude/skills/osint/`
**Кэш результатов:** `/workspace/osint/`
**Кэш ботов:** `/workspace/osint/.bot_urls.json`
**Лог расходов:** `/workspace/osint/.spend_log.json`

---

## 1. Security Rules

1. **Только owner.** OSINT-запросы принимать ТОЛЬКО от создателя (`TG_USER_ID`). Если запрос от НЕ-owner — ответить: "Эта функция доступна только владельцу."
2. **Результаты — только создателю.** Отправлять через `tg_send_message` только в чат с owner.
3. **Не пересылать.** НИКОГДА не пересылать данные третьим лицам без явного ОК создателя.
4. **Не хранить в MEMORY.** НИКОГДА не записывать OSINT-данные в memory_append/memory_log. Исключение: bot_urls.json (технические URL ботов).
5. **Секреты.** НИКОГДА не читать `/data/telethon.session` и не выводить значения `TG_API_ID`/`TG_API_HASH`. Скрипты используют их напрямую из env.
6. **Подтверждение платных запросов.** Перед КАЖДЫМ запросом к платному боту — спросить подтверждение создателя. Формат: "Отправить платный запрос к {бот}? ({тип}: {значение}) | Сегодня потрачено: {N} запросов"
7. **Предупреждение при первом запуске.** При первом OSINT-запросе в сессии — сообщить: "Оба источника (Cilordbot и Sherlock Report) — платные сервисы. Продолжить?"
8. **Очистка.** Не удалять результаты автоматически — они нужны для повторного доступа. Создатель удаляет вручную при необходимости.

---

## 2. State Tracking

На протяжении OSINT-сессии (= одного запроса на пробив от момента получения до отправки отчёта) отслеживать:

```
query_type: username | phone | fio | email | auto_plate | auto_vin | social | document | address | cadastre | ogrn | domain_ip | photo
query_value: нормализованное значение
cilord_status: pending | done | skipped | error | no_balance
sherlock_status: pending | done | skipped | error | no_balance
cilord_bot: текущий username бота Cilordbot (из резолвера)
sherlock_bot: текущий username бота Sherlock Report (из резолвера)
cache_hit: true | false
daily_spend: число запросов за сегодня
```

Обновляй состояние после каждого шага.

---

## 3. Input Detection

Определи тип данных из запроса создателя. Можно использовать утилиту:

```bash
cd /workspace/.claude/skills/osint && python3 osint_utils.py detect "входной текст"
```

Вернёт JSON: `{"query_type": "...", "query_value": "..."}`

### Таблица типов

| Паттерн | query_type | Пример |
|---|---|---|
| @username или username без @ (латиница, 4-32 символа) | username | @durov, durov |
| +7XXXXXXXXXX / 7XXXXXXXXXX / 8XXXXXXXXXX (11 цифр) | phone | +79991234567 |
| Кириллица ФИО + опционально ДД.ММ.ГГГГ | fio | Иванов Иван Иванович 01.01.1990 |
| email@domain | email | user@mail.ru |
| Рус.буквы + цифры + регион (госномер) | auto_plate | В395ОК199 |
| 17 символов латиница+цифры (VIN) | auto_vin | XTA211440C5106924 |
| vk.com/ ok.ru/ instagram.com/ и др. | social | vk.com/durov |
| /passport /vu /snils /inn + цифры | document | /passport 1234567890 |
| /adr + текст | address | /adr Москва, Тверская, 1 |
| XX:XX:XXXXXXX:XXXX (кадастр) | cadastre | 77:01:0004042:6987 |
| 13 цифр (ОГРН) | ogrn | 1107449004464 |
| domain.tld или IP | domain_ip | example.com, 1.1.1.1 |
| Прикреплённое фото/изображение | photo | (файл) |

### Нормализация
- **Телефон:** убрать `+`, заменить `8` -> `7` в начале -> `7XXXXXXXXXX`
- **Username:** убрать `@` -> `username`
- **ФИО:** `Фамилия Имя Отчество ДД.ММ.ГГГГ` (пробел-разделитель)

### Если тип = unknown

Если `detect` вернул `"query_type": "unknown"` — уточнить у создателя:
"Не могу определить тип данных: `{значение}`. Укажи тип: phone / username / fio / email / auto / domain / другое."

---

## 4. Routing — маршрутизация по источникам

Оба бота **ПЛАТНЫЕ**. Перед запросом к каждому — подтверждение создателя.

| query_type | Cilordbot (telelog) | Sherlock Report |
|---|---|---|
| username | основной | дополнительный |
| phone | да | да |
| fio | нет | да |
| email | нет | да |
| auto_plate / auto_vin | нет | да |
| social | нет | да |
| document | нет | да |
| address | нет | да |
| cadastre | нет | да |
| ogrn | нет | да |
| domain_ip | нет | да |
| photo | нет | да (face search) |

**Порядок:** сначала Cilordbot (если поддерживает тип), потом Sherlock Report.

**Цепочка:** если Cilordbot нашёл телефон — предложить использовать его для дополнительного запроса в Sherlock.

**Частичные результаты:** если один бот отработал, а второй дал ошибку — формировать отчёт на основе доступных данных, пометив что второй источник недоступен.

---

## 5. Bot Resolver

Username обоих ботов меняется при блокировках. Скилл резолвит актуальных автоматически.

### Проверка статуса

```bash
cd /workspace/.claude/skills/osint && python3 osint_resolver.py status
```

### Резолв Sherlock Report

```bash
cd /workspace/.claude/skills/osint && python3 osint_resolver.py resolve sherlock
```

Приоритет:
1. **Кэш** из `.bot_urls.json` (< 7 дней) + проверка что бот отвечает на /start
2. **Telegram-канал:** читай посты `@report_sherlok` -> regex `t.me/(\w+)` -> извлечь username бота
3. **Браузер (fallback):** `browser_navigate("https://dc6.sherlock.report/start")` -> `browser_snapshot()` -> извлечь username из страницы

Если скрипт вернул `"method": "needs_browser"` — выполни браузерный fallback вручную:

```
mcp__browser__browser_navigate("https://dc6.sherlock.report/start")
mcp__browser__browser_snapshot()
```

Извлеки username из скриншота, затем сохрани:

```bash
cd /workspace/.claude/skills/osint && python3 osint_resolver.py save sherlock "@new_bot_username"
```

### Резолв Cilordbot (telelog)

```bash
cd /workspace/.claude/skills/osint && python3 osint_resolver.py resolve cilord
```

Приоритет:
1. **Кэш** из `.bot_urls.json` (< 7 дней) + проверка
2. **Браузер:** `browser_navigate("http://bit.ly/4kIt4t9")` -> редирект на telelog.org -> `browser_snapshot()` -> извлечь `t.me/...` ссылку на бота

Если скрипт вернул `"method": "needs_browser"`:

```
mcp__browser__browser_navigate("http://bit.ly/4kIt4t9")
mcp__browser__browser_snapshot()
```

Извлеки t.me/ ссылку, затем сохрани:

```bash
cd /workspace/.claude/skills/osint && python3 osint_resolver.py save cilord "@new_bot_username"
```

### Валидация

После резолва можно проверить отдельно:

```bash
cd /workspace/.claude/skills/osint && python3 osint_resolver.py validate "@bot_username"
```

---

## 6. Cilordbot (telelog) — алгоритм

Бот для Telegram-OSINT: username, ID, телефон -> группы, каналы, сообщения.

### Шаг 6.1 — Кэш

```bash
cd /workspace/.claude/skills/osint && python3 osint_utils.py cache_check "{query_type}" "{query_value}"
```

Если `"cached": true` — прочитай сохранённые файлы через Read, НЕ отправляй платный запрос.

### Шаг 6.1b — Баланс

```bash
cd /workspace/.claude/skills/osint && python3 osint_cilord.py balance
```

Если `balance = 0` или `balance = null`:
```
tg_send_message: "Баланс Cilordbot = 0 (или неизвестен). Пропускаю этот источник."
```
-> `cilord_status = no_balance`, перейти к Sherlock.

### Шаг 6.2 — Подтверждение

Проверить дневной расход:
```bash
cd /workspace/.claude/skills/osint && python3 osint_utils.py spend
```

```
tg_send_message: "Отправить платный запрос к Cilordbot? ({query_type}: {query_value}) | Сегодня: {N} запросов"
```

Ждать явное "да" / "ок" / подтверждение от создателя. Если "нет" -> `cilord_status = skipped`.

### Шаг 6.3 — Отправка запроса

```bash
cd /workspace/.claude/skills/osint && python3 osint_cilord.py send "{query}"
```

Скрипт автоматически:
1. Резолвит бота
2. Отправляет запрос
3. Проходит капчу (кнопка "Click the button")
4. Проверяет баланс (при `no_balance` -> возвращает ошибку)
5. Логирует расход в `.spend_log.json`
6. Сохраняет ответ в `/workspace/osint/{date}_{type}_{value}/cilord_basic.txt`

Возвращает JSON с `message_id`, `text`, `path`, `query_type`, `query_value`.

### Шаг 6.4 — Детализация

Используя `message_id` из предыдущего шага:

```bash
cd /workspace/.claude/skills/osint && python3 osint_cilord.py detail "groups" {message_id} "{query_type}" "{query_value}"
cd /workspace/.claude/skills/osint && python3 osint_cilord.py detail "channels" {message_id} "{query_type}" "{query_value}"
cd /workspace/.claude/skills/osint && python3 osint_cilord.py detail "messages" {message_id} "{query_type}" "{query_value}"
```

**ВАЖНО:** передавай `query_type` и `query_value` для правильного сохранения в кэш-директорию.

Пауза 3 сек между запросами.

Каждая команда кликает соответствующую inline-кнопку и собирает результат.

### Шаг 6.5 — Парсинг

Прочитай все сохранённые файлы через Read:
- `cilord_basic.txt` — ФИО, username, телефон, Telegram ID
- `cilord_groups.txt` — список групп
- `cilord_channels.txt` — список каналов
- `cilord_messages.txt` — образцы сообщений

### Обработка ошибок

| Ситуация | Действие |
|---|---|
| Бот не ответил 30 сек | Скрипт retry x2 автоматически |
| Капча изменилась (нет кнопки) | Уведомить создателя, показать текст ответа |
| Бот забанен / не существует | Запустить резолвер через браузер, повторить |
| `"error": "button_not_found"` | Показать `available_buttons` создателю |
| `"error": "no_balance"` | Уведомить создателя, предложить Sherlock |

---

## 7. Sherlock Report — алгоритм

Комплексный OSINT-бот: телефон, ФИО, email, авто, соцсети, документы, адрес, фото и др.

**Бот принимает текст НАПРЯМУЮ** — без меню и кнопок выбора типа. Кидаешь телефон — ищет по телефону.

### Шаг 7.0 — Первый запуск (setup)

При первом использовании в сессии:

```bash
cd /workspace/.claude/skills/osint && python3 osint_sherlock.py setup
```

Выполняет: подписку на `@report_sherlok`, `/start`, проверку подписки.

### Шаг 7.1 — Баланс

```bash
cd /workspace/.claude/skills/osint && python3 osint_sherlock.py balance
```

Скрипт использует 3 стратегии (кнопка на последнем сообщении -> /start -> /profile).

Вернёт JSON с `balance`, `topup_available`, и опционально `message`.

Если `balance = 0`:
```
tg_send_message: "Баланс Sherlock Report = 0. Нужно пополнить. Тарифы: 15/$3, 75/$12, 300/$42, 1000/$100. Пополнить?"
```
-> Если создатель хочет пополнить — перейти к **секции 8 (Balance & Top-up)**.
-> Иначе `sherlock_status = no_balance`, перейти к синтезу без Sherlock.

### Шаг 7.2 — Подтверждение

```bash
cd /workspace/.claude/skills/osint && python3 osint_utils.py spend
```

```
tg_send_message: "Отправить платный запрос к Sherlock Report? Баланс: {N}. ({query_type}: {query_value}) | Сегодня: {M} запросов"
```

### Шаг 7.3 — Отправка запроса

Формат отправки по типу данных:

| query_type | Что отправить боту | Пример |
|---|---|---|
| phone | `7XXXXXXXXXX` | `79991234567` |
| fio | `Фамилия Имя Отчество ДД.ММ.ГГГГ` | `Иванов Иван Иванович 01.01.1990` |
| email | `email@domain` | `user@mail.ru` |
| auto_plate | `БУКВЫ+ЦИФРЫ+РЕГИОН` | `В395ОК199` |
| auto_vin | `VIN` | `XTA211440C5106924` |
| social | ссылка | `vk.com/durov` |
| username | `@username` | `@durov` |
| document | команда | `/passport 1234567890` |
| address | команда | `/adr Москва, Тверская, 1` |
| cadastre | номер | `77:01:0004042:6987` |
| ogrn | номер | `1107449004464` |
| domain_ip | текст | `example.com` |
| photo | отправить файл | (см. ниже) |

**Фото (face search):** создатель присылает фото -> скачать через `tg_download_media` -> получить путь к файлу -> передать в скрипт:

```bash
cd /workspace/.claude/skills/osint && python3 osint_sherlock.py query "photo" "/path/to/downloaded/photo.jpg"
```

Скрипт отправит файл через `send_file()`.

**Для всех остальных типов:**

```bash
cd /workspace/.claude/skills/osint && python3 osint_sherlock.py query "{query_type}" "{query_value}"
```

Скрипт собирает ВСЕ сообщения ответа (бот может ответить несколькими подряд), конкатенирует и сохраняет. Логирует расход.

### Обработка ошибок

| Ситуация | Действие |
|---|---|
| Бот не ответил | retry x2 с увеличением таймаута (60->90->120 сек) |
| `"error": "no_balance"` | Уведомить создателя, показать тарифы, предложить пополнение |
| FloodWaitError | Пауза N секунд (из ошибки), retry |
| Бот забанен | Запустить резолвер, повторить |

---

## 8. Balance & Top-up

### Проверка баланса

**Cilordbot:**
```bash
cd /workspace/.claude/skills/osint && python3 osint_cilord.py balance
```

**Sherlock Report:**
```bash
cd /workspace/.claude/skills/osint && python3 osint_sherlock.py balance
```

### Дневной расход

```bash
cd /workspace/.claude/skills/osint && python3 osint_utils.py spend
```

Вернёт: `{"date": "...", "total_credits": N, "query_count": M}`

### Тарифы Sherlock Report

| Запросов | Цена |
|---|---|
| 15 | $3 |
| 75 | $12 |
| 300 | $42 |
| 1000 | $100 |

### Процесс пополнения Sherlock

1. Навигация к оплате:
```bash
cd /workspace/.claude/skills/osint && python3 osint_sherlock.py topup
```

Вернёт JSON с `text` (инструкции) и `buttons` (доступные кнопки тарифов).

2. Показать создателю результат:
```
tg_send_message: "Доступные тарифы Sherlock Report:\n{текст из ответа}\n\nКнопки: {список кнопок}\n\nДля оплаты необходимо перейти в бот: @{sherlock_bot} и нажать нужную кнопку оплаты."
```

3. **НЕ кликать кнопки оплаты автоматически.** Только показать информацию. Оплата — действие создателя вручную.

### Тарифы Cilordbot

Тарифы Cilordbot можно узнать только в самом боте. Если баланс 0:
```
tg_send_message: "Баланс Cilordbot = 0. Для пополнения перейдите в бот: @{cilord_bot}"
```

---

## 9. Caching

### Проверка кэша (ПЕРЕД каждым запросом)

```bash
cd /workspace/.claude/skills/osint && python3 osint_utils.py cache_check "{query_type}" "{query_value}"
```

- Если `"cached": true` — прочитай файлы через Read, НЕ делай платный запрос
- Если `"cached": false` — выполняй запрос

### Структура кэша

```
/workspace/osint/2026-02-12_phone_79991234567/
  cilord_basic.txt
  cilord_groups.txt
  cilord_channels.txt
  cilord_messages.txt
  sherlock_result.txt
  report.md
```

### Правила
- Кэш считается свежим если возраст файлов < 24 часов
- **НИКОГДА не повторять платные запросы если кэш свежий**
- Создатель может запросить обновление: "обнови данные по ..." -> игнорировать кэш

---

## 10. Synthesis & Report

После сбора данных из всех источников:

### Шаг 10.1 — Чтение результатов

Прочитай все файлы из кэш-директории через Read tool.

### Шаг 10.2 — Синтез

Объедини данные из обоих источников:
- Убери дубликаты (один и тот же телефон из Cilordbot и Sherlock)
- Отметь источник каждой единицы данных
- Выдели наиболее ценную информацию

**Частичные результаты:** если один из ботов недоступен (no_balance, error, skipped) — формируй отчёт на основе доступных данных. Укажи какой источник не использовался и почему.

### Шаг 10.3 — Формирование отчёта

Формат:

```
OSINT-отчёт: {query}
Дата: {дата}
Источники: {список использованных}
Потрачено запросов: {число}

Персональные данные
- ФИО: ...
- Дата рождения: ...
- Телефон(ы): ...
- Telegram: @... (ID: ...)

Соцсети
- VK: ...
- Instagram: ...

Telegram-активность (из Cilordbot)
- Группы ({N}): ...
- Каналы ({N}): ...
- Примеры сообщений: ...

Транспорт (если есть)
- ...

Документы (если есть)
- ...

Юридические лица (если есть)
- ...

Примечания
- Какие источники не дали результат
- Что не удалось проверить
```

### Шаг 10.4 — Отправка

Если отчёт > 4000 символов — разбей на части (tg_send_message ограничен 4096).

```
tg_send_message(message="{отчёт}")
```

### Шаг 10.5 — Сохранение

Сохрани отчёт в кэш-директорию:

```
Write: /workspace/osint/{cache_dir}/report.md
```

---

## 11. Error Handling

| Ситуация | Действие |
|---|---|
| Бот не отвечает 30 сек | Скрипты retry x2 автоматически, потом skip |
| Бот забанен/сменился | resolver -> новый бот -> retry |
| Капча изменилась | Уведомить создателя, показать текст ответа |
| Баланс = 0 (любой бот) | Уведомить создателя, показать тарифы, предложить пополнение (секция 8) |
| Неизвестный формат ответа | Сохранить raw text, показать создателю как есть |
| FloodWaitError | Пауза N сек, retry (скрипт обрабатывает автоматически) |
| UserBannedError | Уведомить: "Аккаунт заблокирован в этом боте" |
| Telethon session не найден | Уведомить: "Нет Telethon-сессии. Настройте авторизацию." |
| Env vars не заданы | Уведомить: "Не заданы TG_API_ID/TG_API_HASH" |
| Резолвер не нашёл бота | Попробовать все методы (кэш -> канал -> браузер), уведомить если все провалились |
| Запрос от НЕ-owner | Отклонить: "Эта функция доступна только владельцу" |
| Неизвестный query_type | Спросить создателя тип (см. секцию 3) |
| Python-скрипт вернул `"error"` | Прочитать поле `error`, действовать по таблице выше |
| Один бот OK, другой error | Формировать отчёт из доступных данных (секция 10.2) |

---

## 12. Communication Format

### Язык
По умолчанию — **русский**. Переключайся на английский только если создатель пишет на английском.

### Промежуточные сообщения
НЕ отправлять промежуточные статусы ("Ищу бота...", "Отправил запрос..."). Отправлять только:
1. Запрос подтверждения платного запроса
2. Итоговый отчёт
3. Сообщения об ошибках, требующих действий создателя

### Длинные сообщения
Если > 4000 символов — разбить на логические части:
- Часть 1: персональные данные + соцсети
- Часть 2: Telegram-активность
- Часть 3: остальное + примечания

---

## 13. Full Workflow (end-to-end)

```
Создатель: "Пробей @durov"
    |
    v
1. Проверить: запрос от owner? -> да
    |
    v
2. Первый OSINT в сессии? -> "Оба источника платные. Продолжить?"
   Создатель: "да"
    |
    v
3. Определить тип: python3 osint_utils.py detect "@durov"
   -> {"query_type": "username", "query_value": "durov"}
   (Если unknown -> уточнить у создателя)
    |
    v
4. Проверить кэш: python3 osint_utils.py cache_check "username" "durov"
   -> {"cached": false}
    |
    v
5. Резолвить ботов: python3 osint_resolver.py status
   (Если needs_browser -> browser_navigate -> browser_snapshot -> save)
    |
    v
6. Routing: username -> Cilordbot да, Sherlock да
    |
    v
=== CILORDBOT ===
    |
    v
7a. Проверить баланс: python3 osint_cilord.py balance
    (Если 0 -> skip, перейти к Sherlock)
    |
    v
7b. Дневной расход: python3 osint_utils.py spend
    |
    v
7c. tg_send_message: "Отправить платный запрос к Cilordbot? (username: durov) | Сегодня: 3 запроса"
    Создатель: "да"
    |
    v
8. python3 osint_cilord.py send "@durov"
   -> капча -> базовая карточка -> save
    |
    v
9. python3 osint_cilord.py detail "groups" {msg_id} "username" "durov"
   (пауза 3 сек)
   python3 osint_cilord.py detail "channels" {msg_id} "username" "durov"
   (пауза 3 сек)
   python3 osint_cilord.py detail "messages" {msg_id} "username" "durov"
    |
    v
=== SHERLOCK REPORT ===
    |
    v
10a. python3 osint_sherlock.py setup  (первый раз в сессии)
    |
    v
10b. python3 osint_sherlock.py balance
     (Если 0 -> предложить пополнение -> skip или topup)
    |
    v
10c. tg_send_message: "Отправить платный запрос к Sherlock Report? Баланс: 42. (username: durov) | Сегодня: 4 запроса"
     Создатель: "да"
    |
    v
11. python3 osint_sherlock.py query "username" "@durov"
    -> сбор множественных ответов -> save
    |
    v
=== СИНТЕЗ ===
    |
    v
12. Read все файлы из /workspace/osint/...
    |
    v
13. Синтезировать профиль -> сформировать отчёт
    |
    v
14. tg_send_message(message=отчёт)  # ТОЛЬКО создателю
    |
    v
15. Write: /workspace/osint/{dir}/report.md
```

---

## 14. CLI Reference

### osint_utils.py

```bash
# Определить тип запроса
python3 osint_utils.py detect "текст"

# Проверить кэш
python3 osint_utils.py cache_check "query_type" "query_value"

# Дневной расход
python3 osint_utils.py spend
```

### osint_resolver.py

```bash
# Статус обоих ботов
python3 osint_resolver.py status

# Резолвить бота
python3 osint_resolver.py resolve sherlock
python3 osint_resolver.py resolve cilord

# Сохранить username вручную
python3 osint_resolver.py save sherlock "@new_bot"
python3 osint_resolver.py save cilord "@new_bot"

# Проверить бота
python3 osint_resolver.py validate "@bot_username"
```

### osint_cilord.py

```bash
# Проверить баланс
python3 osint_cilord.py balance

# Отправить запрос
python3 osint_cilord.py send "запрос"

# Детализация (groups/channels/messages)
python3 osint_cilord.py detail "groups" {message_id} [query_type] [query_value]
```

### osint_sherlock.py

```bash
# Первоначальная настройка
python3 osint_sherlock.py setup

# Проверить баланс
python3 osint_sherlock.py balance

# Отправить запрос
python3 osint_sherlock.py query "query_type" "query_value"

# Навигация к оплате
python3 osint_sherlock.py topup
```

**Все команды запускать из директории:** `cd /workspace/.claude/skills/osint && ...`
