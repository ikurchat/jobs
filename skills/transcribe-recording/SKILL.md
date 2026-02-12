---
name: transcribe-recording
description: Use this skill to transcribe browser audio recordings. Triggers: "транскрибируй запись", "что было на встрече", "transcribe recording", "сделай сводку встречи", "что говорили", "расшифруй аудио", "recording info", "покажи записи".
tools: Bash
---

# Transcribe Recording

Browser контейнер непрерывно записывает всё аудио через ffmpeg в 10-минутные WAV-чанки в `/recordings/`. Файлы хранятся 24 часа (автоочистка). Этот skill транскрибирует нужные чанки через OpenAI Whisper API.

## Когда НЕ активировать

- Голосовые сообщения в Telegram (они обрабатываются встроенным Whisper, не этим скиллом)
- Текстовые файлы, PDF, изображения
- Видео без аудиодорожки

## Формат файлов

```
/recordings/chunk_YYYYMMDD_HHMMSS.mp3
```

- Mono 16kHz WAV, ~2.4 MB на 10-мин чанк
- Timestamp в имени = момент начала записи сегмента

## Algorithm

### 1. Определи период

Если пользователь указал время — используй его. Иначе — последние 60 минут.

### 2. Найди чанки

```bash
ls -la /recordings/chunk_*.mp3 2>/dev/null | sort
```

Для фильтрации по времени (например, последние 60 минут):
```bash
find /recordings -name "chunk_*.mp3" -mmin -60 -type f | sort
```

Если файлов нет — сообщи пользователю что записей нет.

### 3. Отфильтруй активный чанк

Файл, который сейчас записывается, не трогай. Определи его так:
```bash
find /recordings -name "chunk_*.mp3" -mmin -1 -type f
```
Исключи этот файл из транскрибации.

### 4. Транскрибируй через Whisper API

Для каждого чанка:
```bash
curl -s https://api.openai.com/v1/audio/transcriptions \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -F model="whisper-1" \
  -F language="ru" \
  -F file="@/recordings/chunk_YYYYMMDD_HHMMSS.mp3"
```

Если задан `$HTTP_PROXY` — добавь `--proxy $HTTP_PROXY`.

Ответ — JSON с полем `text`. Пустой text означает тишину — пропускай.

### 5. Собери результат

Объедини тексты в хронологическом порядке с метками времени:
```
[14:30] текст чанка 1

[14:40] текст чанка 2
```

### 6. Сделай сводку

После транскрибации — сделай краткую сводку: основные темы, решения, action items.

## Info Mode

Если пользователь спрашивает "покажи записи" / "recording info" — просто покажи список файлов и общий размер:
```bash
ls -lh /recordings/chunk_*.mp3 2>/dev/null | tail -20
du -sh /recordings/ 2>/dev/null
```

## Important Notes

- Максимальный размер файла для Whisper API — 25 MB. Наши чанки ~2.4 MB, укладываемся.
- Не транскрибируй файл, который ещё записывается (самый свежий по mtime).
- Если чанков много (>10), предупреди пользователя что это займёт время.
- OPENAI_API_KEY доступен в env.
- Если proxy настроен ($HTTP_PROXY), используй его в curl.
