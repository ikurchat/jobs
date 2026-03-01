---
name: movie-rec
description: >
  Use when user asks to recommend a movie, suggest what to watch.
  Triggers: "фильм", "кино", "что посмотреть", "посоветуй фильм",
  "рекомендуй кино", "movie", "что глянуть", "посоветуй что посмотреть",
  "подскажи фильм"
tools:
  - mcp__browser__browser_navigate
  - mcp__browser__browser_snapshot
  - mcp__browser__browser_click
  - mcp__jobs__tg_send_message
  - mcp__jobs__tg_read_chat
---

# movie-rec — рекомендация фильмов + ссылка на просмотр

## Алгоритм

### Шаг 1. Подбор

Предложи 10 фильмов. Если пользователь указал жанр, настроение или тему — учти.

Формат:
```
1. Название (год) — жанр — 1 строка почему стоит
2. ...
```

Правила:
- Разнообразие: разные жанры, десятилетия, страны.
- Без лекций и длинных описаний. Одна строка на фильм.

### Шаг 2. Выбор

Жди номер или название от пользователя. Не переспрашивай лишнего.

### Шаг 3. Поиск на Кинопоиске

1. `browser_navigate("https://www.kinopoisk.ru/index.php?kp_query=Название+Год")`
2. `browser_snapshot()`
3. В snapshot найди ссылку на страницу фильма — формат `/film/XXXXX/`.

### Шаг 4. Конверсия ссылки

Замени `kinopoisk.ru` → `kinopoisk.vip` в найденном URL.

Результат: `https://www.kinopoisk.vip/film/XXXXX/`

### Шаг 5. Отправка

Отправь пользователю:
```
tg_send_message: "Название (год)\nhttps://www.kinopoisk.vip/film/XXXXX/"
```
