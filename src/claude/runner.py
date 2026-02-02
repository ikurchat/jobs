import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from src.config import settings


@dataclass
class ClaudeResponse:
    """Ответ от Claude Code CLI."""

    content: str
    tool_calls: list[dict] = field(default_factory=list)
    cost_usd: float = 0.0
    duration_ms: int = 0
    is_error: bool = False


async def run_claude(
    prompt: str,
    cwd: str | Path | None = None,
    timeout: int = 300,
) -> ClaudeResponse:
    """
    Запуск Claude Code CLI с JSON output.

    Args:
        prompt: Промпт для Claude.
        cwd: Рабочая директория (по умолчанию /workspace).
        timeout: Таймаут в секундах.

    Returns:
        ClaudeResponse с результатом выполнения.
    """
    if cwd is None:
        cwd = settings.workspace_dir

    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HTTP_PROXY"] = settings.http_proxy
    env["HTTPS_PROXY"] = settings.http_proxy

    # API key опционален при OAuth авторизации
    if settings.anthropic_api_key:
        env["ANTHROPIC_API_KEY"] = settings.anthropic_api_key

    cmd = [
        "claude",
        "--output-format",
        "json",
        "--dangerously-skip-permissions",
        "-p",
        prompt,
    ]

    logger.debug(f"Running Claude CLI: {' '.join(cmd[:4])}...")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return ClaudeResponse(
            content=f"Таймаут: Claude не ответил за {timeout} секунд",
            is_error=True,
        )

    if proc.returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace").strip()
        logger.error(f"Claude CLI error: {error_msg}")
        return ClaudeResponse(
            content=f"Ошибка Claude CLI: {error_msg}",
            is_error=True,
        )

    # Парсим JSON output
    raw_output = stdout.decode("utf-8", errors="replace")

    return _parse_claude_output(raw_output)


def _parse_claude_output(raw_output: str) -> ClaudeResponse:
    """Парсит JSON output от Claude Code CLI."""
    try:
        data = json.loads(raw_output)
    except json.JSONDecodeError:
        # Если не JSON, возвращаем как есть
        return ClaudeResponse(content=raw_output.strip())

    # Claude Code CLI возвращает структуру с result
    if isinstance(data, dict):
        result = data.get("result", "")
        cost = data.get("cost_usd", 0.0)
        duration = data.get("duration_ms", 0)

        # result может быть строкой или списком блоков
        if isinstance(result, str):
            content = result
        elif isinstance(result, list):
            # Собираем текстовый контент из блоков
            text_parts = []
            for block in result:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            content = "\n".join(text_parts)
        else:
            content = str(result)

        return ClaudeResponse(
            content=content,
            cost_usd=cost,
            duration_ms=duration,
        )

    return ClaudeResponse(content=str(data))
