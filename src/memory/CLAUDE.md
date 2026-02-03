# memory/ — Система памяти

## Три уровня памяти

```
/workspace/
├── MEMORY.md              # Долгосрочная (факты, предпочтения)
├── HEARTBEAT.md           # Чеклист для проактивных проверок
├── memory/
│   └── 2025-02-03.md      # Дневные логи (append-only)
└── sessions/
    └── 2025-02-03-task.md # Транскрипты диалогов
```

## Файлы

| Файл | Описание |
|------|----------|
| `storage.py` | Файловое хранилище (read/write markdown) |
| `index.py` | Векторный + BM25 поиск (SQLite + sqlite-vec) |
| `tools.py` | MCP инструменты для Claude |

## MemoryStorage (storage.py)

### MEMORY.md — долгосрочная память
```python
read_memory() → str
append_to_memory(content) → добавляет с timestamp
```
**Когда использовать:** предпочтения, решения, факты о пользователе

### Daily logs — дневные логи
```python
read_daily_log(date?) → str
append_to_daily_log(content) → добавляет с временем
get_recent_context(days=2) → контекст за N дней
```
**Когда использовать:** прогресс, заметки, контекст работы

### Sessions — транскрипты
```python
save_session(slug, content) → Path
append_to_session(slug, role, content)
```
**Когда использовать:** полная история конкретного разговора

## MemoryIndex (index.py)

### Гибридный поиск
- **70% Vector** (OpenAI embeddings + sqlite-vec)
- **30% BM25** (SQLite FTS5)

### Параметры
```python
CHUNK_SIZE = 400 tokens (~1600 chars)
CHUNK_OVERLAP = 80 tokens
```

### Методы
```python
index_file(file_path) → int (chunks indexed)
index_all(files) → int (total chunks)
search(query, limit=5) → list[SearchResult]
```

### SearchResult
```python
@dataclass
class SearchResult:
    content: str
    file_path: str
    line_start: int
    line_end: int
    score: float  # 0.0 - 1.0
```

## MCP Tools (tools.py)

| Tool | Описание |
|------|----------|
| `memory_search(query)` | Поиск в памяти (vector + BM25) |
| `memory_read(path)` | Прочитать файл памяти |
| `memory_append(content)` | Добавить в MEMORY.md |
| `memory_log(content)` | Добавить в дневной лог |
| `memory_context()` | MEMORY.md + последние 2 дня |
| `memory_reindex()` | Переиндексировать всё |

## Singletons

```python
get_storage() → MemoryStorage  # Файловое хранилище
get_index() → MemoryIndex      # Векторный индекс
```

## Fallback

Если OpenAI API недоступен или sqlite-vec не установлен:
- Поиск работает только через BM25 (FTS5)
- Косинусное сходство вычисляется в Python
