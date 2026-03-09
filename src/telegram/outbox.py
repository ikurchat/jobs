"""
Outbox — очередь исходящих сообщений с dedup и rate limiting.

Все отправки в Telegram идут через Outbox:
- Dedup: одинаковый текст одному chat_id в течение DEDUP_WINDOW — пропускается
- Rate limit: не чаще RATE_LIMIT_INTERVAL между сообщениями одному chat_id
- Backoff: при FloodWaitError/429 — пауза и повтор
"""

import asyncio
import hashlib
import time
from collections import defaultdict
from typing import Any, Callable, Awaitable

from loguru import logger

# Настройки
DEDUP_WINDOW = 60.0  # Окно дедупликации (секунды)
RATE_LIMIT_INTERVAL = 1.0  # Мин. интервал между сообщениями одному chat_id (секунды)
MAX_RETRIES = 3  # Макс. ретраев при rate limit
DEDUP_HISTORY_SIZE = 50  # Макс. хранимых хешей на chat_id


def _text_hash(text: str) -> str:
    """Короткий хеш текста для dedup."""
    return hashlib.md5(text.encode()).hexdigest()[:12]


class Outbox:
    """Очередь исходящих с dedup и rate limiting."""

    def __init__(self) -> None:
        # {chat_id: [(hash, timestamp), ...]}
        self._sent: dict[int, list[tuple[str, float]]] = defaultdict(list)
        # {chat_id: last_send_time}
        self._last_send: dict[int, float] = defaultdict(float)
        # Per-chat lock для сериализации отправок
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _is_duplicate(self, chat_id: int, text: str) -> bool:
        """Проверяет, отправлялся ли такой же текст недавно."""
        h = _text_hash(text)
        now = time.monotonic()
        history = self._sent[chat_id]

        # Чистим старые записи
        history[:] = [(hh, t) for hh, t in history if now - t < DEDUP_WINDOW]

        for hh, _ in history:
            if hh == h:
                return True
        return False

    def _record_sent(self, chat_id: int, text: str) -> None:
        """Записывает отправку для dedup."""
        h = _text_hash(text)
        now = time.monotonic()
        history = self._sent[chat_id]
        history.append((h, now))
        # Ограничиваем размер
        if len(history) > DEDUP_HISTORY_SIZE:
            history[:] = history[-DEDUP_HISTORY_SIZE:]

    async def _wait_rate_limit(self, chat_id: int) -> None:
        """Ждёт если слишком быстро шлём."""
        elapsed = time.monotonic() - self._last_send[chat_id]
        if elapsed < RATE_LIMIT_INTERVAL:
            await asyncio.sleep(RATE_LIMIT_INTERVAL - elapsed)

    async def send(
        self,
        chat_id: int,
        text: str,
        send_fn: Callable[..., Awaitable],
        *args,
        skip_dedup: bool = False,
        **kwargs,
    ) -> Any:
        """Отправляет сообщение через очередь.

        Args:
            chat_id: ID чата
            text: Текст сообщения (для dedup)
            send_fn: Функция отправки (transport.send_message, transport.reply, etc.)
            *args, **kwargs: Аргументы для send_fn
            skip_dedup: Пропустить проверку дубликатов

        Returns:
            message_id или None если дубль/ошибка
        """
        async with self._locks[chat_id]:
            # Dedup
            if not skip_dedup and self._is_duplicate(chat_id, text):
                logger.debug(f"Outbox dedup: skipped duplicate to {chat_id}")
                return None

            # Rate limit
            await self._wait_rate_limit(chat_id)

            # Отправка с retry при flood
            for attempt in range(MAX_RETRIES):
                try:
                    result = await send_fn(*args, **kwargs)
                    self._last_send[chat_id] = time.monotonic()
                    self._record_sent(chat_id, text)
                    return result
                except Exception as e:
                    retry_after = _extract_retry_after(e)
                    if retry_after and attempt < MAX_RETRIES - 1:
                        logger.warning(f"Outbox flood wait {retry_after}s for chat {chat_id}")
                        await asyncio.sleep(retry_after)
                        continue
                    raise

        return None


def _extract_retry_after(e: Exception) -> float | None:
    """Извлекает retry_after из разных типов flood-ошибок."""
    # Telethon: FloodWaitError
    if hasattr(e, "seconds"):
        return float(e.seconds)
    # aiogram: TelegramRetryAfter
    if hasattr(e, "retry_after"):
        return float(e.retry_after)
    # Строковый fallback
    err_str = str(e).lower()
    if "flood" in err_str or "429" in err_str or "too many" in err_str:
        return 2.0  # Дефолтная пауза
    return None


# Глобальный singleton
_outbox: Outbox | None = None


def get_outbox() -> Outbox:
    global _outbox
    if _outbox is None:
        _outbox = Outbox()
    return _outbox
