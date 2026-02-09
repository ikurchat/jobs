"""
Updater client — двухшаговое обновление через /update команду.

Первый вызов: проверяет наличие обновлений и показывает коммиты.
Второй вызов: запускает обновление (pull + build + restart).
"""

import asyncio
from dataclasses import dataclass, field

import aiohttp
from loguru import logger

UPDATER_URL = "http://updater:9100"


@dataclass
class Updater:
    _pending: bool = field(default=False, init=False)

    async def handle(self) -> str:
        """Вызывается при /update. Возвращает текст ответа."""
        if self._pending:
            self._pending = False
            asyncio.create_task(self._trigger_update())
            return "\U0001f504 Устанавливаю обновление..."

        info = await self._check()

        if "error" in info:
            return f"\u274c Ошибка: {info['error']}"

        if not info["commits"]:
            return f"\u2705 Последняя версия ({info['current'][:7]})"

        self._pending = True
        lines = [f"- [{c['hash'][:7]}] {c['message']}" for c in info["commits"]]
        return (
            "\U0001f918 Доступно обновление\n\n"
            + "\n".join(lines)
            + "\n\nЧтобы установить, напишите /update ещё раз."
        )

    async def _check(self) -> dict:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{UPDATER_URL}/check") as resp:
                return await resp.json()

    async def _trigger_update(self) -> None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{UPDATER_URL}/update") as resp:
                    data = await resp.json()
                    if "error" in data:
                        logger.error(f"Update failed: {data['error']}")
        except Exception as e:
            logger.error(f"Update request failed: {e}")
