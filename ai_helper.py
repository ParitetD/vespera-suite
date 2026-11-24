"""AI Helper — сбор контекста из логов/терминала и запросы к LLM (OpenAI-совместимый API).

Используется:
- AI Copilot при ошибках модулей (анализ Traceback из logs/app.log + вывод терминала),
- WebSocket /ws/ai-chat (стриминг ответа через ai_stream).
"""

from pathlib import Path
from typing import AsyncIterator, List

from loguru import logger

from app.config import BASE_DIR, get_settings

SYSTEM_PROMPT = """Ты — старший DevOps-инженер и архитектор FastAPI-приложений (Python/pydantic/SQLAlchemy/httpx).
Твоя задача — анализировать ошибки локального OSINT-инструмента Vespera Search Suite:

1. Читай предоставленный контекст: логи приложения (logs/app.log), вывод терминала (если есть) и вопрос пользователя.
2. Находи причину ошибки (Traceback, HTTPException, timeout, ConnectionError и т.д.).
3. Предлагай конкретные исправления: добавить try/except, повысить таймаут, добавить retry, изменить парсинг и т.д.
4. Выводи код для вставки (python/js), но НИКОГДА не предлагай запуск приложения, перезапись файлов или перезагрузку.
5. Отвечай на русском языке, лаконично: проблема → причина → решение (код) → дополнительные советы.
6. Если ошибка окружения (нет ключей, зависимостей) — скажи как установить или настроить.
"""


class TerminalRing:
    """Кольцевой буфер вывода терминала: последние N строк для AI-контекста."""

    def __init__(self, maxlen: int = 300):
        self.maxlen = maxlen
        self._lines: List[str] = []

    def add(self, text: str) -> None:
        for line in text.replace("\r", "").split("\n"):
            line = line.strip("\x00")
            if line.strip():
                self._lines.append(line[-200:])
        if len(self._lines) > self.maxlen:
            self._lines = self._lines[-self.maxlen:]

    def get_tail(self, lines: int = 200) -> str:
        return "\n".join(self._lines[-lines:])


def read_log_tail(lines: int = 120) -> List[str]:
    p = Path(BASE_DIR) / "logs" / "app.log"
    if not p.exists():
        return []
    try:
        return p.read_text(errors="replace").splitlines()[-lines:]
    except Exception:
        return []


def build_context(
    log_lines: List[str],
    terminal_tail: str = "",
    user_question: str = "",
) -> str:
    parts: List[str] = []
    parts.append("=== ЛОГИ ПРИЛОЖЕНИЯ (logs/app.log, последние 120 строк) ===")
    parts.append("\n".join(log_lines[-120:]) or "(пусто)")
    if terminal_tail:
        parts.append("\n=== ВЫВОД ТЕРМИНАЛА (последние 200 строк) ===")
        parts.append(terminal_tail)
    parts.append("\n=== ВОПРОС ПОЛЬЗОВАТЕЛЯ ===")
    parts.append(user_question or "(нет)")
    return "\n".join(parts)


async def ai_stream(context: str) -> AsyncIterator[str]:
    """Асинхронный генератор чанков ответа LLM (стриминг)."""
    settings = get_settings()
    if not settings.openai_api_key:
        yield "⚠️ Для работы AI Copilot добавьте OPENAI_API_KEY в .env."
        return
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.ai_base_url or None,
        )
        stream = await client.chat.completions.create(
            model=settings.ai_model or "gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
            stream=True,
            max_tokens=2000,
            temperature=0.7,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue  # финальный usage-чанк без delta — пропускаем
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content
    except Exception as exc:
        logger.opt(exception=True).error(f"[ai_helper] LLM error: {exc}")
        yield f"⚠️ Ошибка запроса к AI: {exc}"
