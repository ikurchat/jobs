---
name: schedule-meeting
description: Use this skill when user asks to "schedule a meeting", "договорись о встрече", "назначь встречу", "согласуй время встречи", "meet with someone", or mentions scheduling time with another person.
tools: Read, Bash
---

# Schedule Meeting

Согласование встречи с пользователем через cross-session communication.

## Algorithm

### 1. Parse Request

Из запроса извлеки:
- **Участник**: @username, имя или ID
- **Временные слоты**: диапазон времени владельца (например "12:00-20:00")
- **Дата**: если указана, иначе "завтра"

### 2. Find User

```
resolve_user("@masha")
```

Если не найден — сообщи владельцу.

### 3. Create Conversation Task

```
start_conversation(
  user="@masha",
  task_type="meeting",
  title="Встреча {дата}",
  context={
    "date": "завтра",
    "owner_slots": "12:00-20:00",
    "purpose": "если указана цель"
  },
  initial_message="Привет! Нужно выбрать время для встречи.
                   Удобно завтра с 12:00 до 20:00.
                   В какое время тебе подходит?"
)
```

### 4. Wait for Result

Результат придёт автоматически через уведомление когда user session соберёт информацию.

### 5. After Confirmation

Когда получишь уведомление о завершении согласования:

1. Создай напоминание за 5 минут до встречи:
```
schedule_task(
  prompt="Встреча с @masha через 5 минут. Создай ссылку Яндекс Телемост и отправь обоим.",
  time="согласованное время минус 5 минут"
)
```

2. Уведоми владельца о подтверждении.

## Tools Used

- `resolve_user(query)` — найти пользователя
- `start_conversation(user, task_type, title, context, initial_message)` — начать согласование
- `schedule_task(prompt, time)` — создать напоминание
- `send_to_user(user, message)` — уведомить участников

## User Session Instructions

Ты помогаешь согласовать время встречи.

### Твоя задача

1. Спроси у пользователя удобное время из предложенных слотов
2. Если время не подходит — уточни какое подходит
3. Когда время согласовано — обнови результат:

```
update_conversation(
  task_id="текущий task_id",
  status="completed",
  result={
    "confirmed_time": "15:00",
    "confirmed_date": "завтра",
    "user_comment": "если пользователь что-то добавил"
  }
)
```

### Правила

- Будь кратким
- Не предлагай время вне указанных слотов
- Если пользователь не может — запиши это в result с status="cancelled"

## Examples

### Example 1: Explicit trigger

**Input:** `/schedule-meeting @masha завтра 12:00-20:00`

**Actions:**
1. `resolve_user("@masha")` → found
2. `start_conversation(...)` → message sent to @masha
3. Reply to owner: "Запрос на встречу отправлен @masha"

### Example 2: Implicit trigger

**Input:** "Договорись с Петей о встрече на эту неделю, мне удобно в четверг после 14"

**Actions:**
1. Parse: participant="Петя", date="четверг", slots="14:00-23:59"
2. `resolve_user("Петя")` → found @petya
3. `start_conversation(...)` with context
