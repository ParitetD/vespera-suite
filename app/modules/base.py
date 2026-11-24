"""BaseModule — абстрактный класс модуля + safe_search.

Контракт:
- `supported_inputs`: список типов, которые модуль принимает ("username",
  "email", "phone", "social", "photo", "metadata").
- `search(query) -> List[dict]`: делает запрос, возвращает нормализованные
  результаты (схема app.utils.normalizer.norm).
- `safe_search` оборачивает search: try/except + timeout + rate-limit.
  Ошибка одного модуля не ломает остальные — это цель архитектуры.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from loguru import logger

from app.config import get_settings
from app.core.rate_limiter import RateLimiter


class BaseModule(ABC):
    name: str = "base"
    supported_inputs: List[str] = []
    timeout: float = 30.0

    def __init__(self, limiter: Optional[RateLimiter] = None):
        self.limiter = limiter or RateLimiter(get_settings().rate_limit_default)
        self.progress: List[str] = []   # статус-сообщения для живого UI
        self._progress_sent: int = 0

    def domain(self, query: Optional[Dict[str, Any]] = None) -> str:
        """Домен для per-domain rate-limit (переопределяется, если нужен)."""
        return ""

    async def acquire(self, query: Optional[Dict[str, Any]] = None) -> None:
        key = self.domain(query)
        if key:
            await self.limiter.acquire(key)

    async def safe_search(self, query: Dict[str, Any]) -> Dict[str, Any]:
        """Безопасный запуск модуля. Возвращает:

        {"module": name, "status": "ok"|"error"|"skipped", "data": [...], "error": ...}
        """
        qtype = query.get("type")
        if qtype not in self.supported_inputs:
            return {
                "module": self.name,
                "status": "skipped",
                "data": [],
                "error": f"type '{qtype}' not supported",
            }
        try:
            await self.acquire(query)
            data = await asyncio.wait_for(self.search(query), timeout=self.timeout)
            return {"module": self.name, "status": "ok", "data": list(data or []), "error": None}
        except asyncio.TimeoutError:
            logger.warning(f"[{self.name}] timeout after {self.timeout}s")
            return {
                "module": self.name,
                "status": "error",
                "data": [],
                "error": f"timeout > {self.timeout}s",
            }
        except Exception as exc:  # падение одного модуля не ломает остальные
            logger.opt(exception=True).error(f"[{self.name}] failed: {exc}")
            return {
                "module": self.name,
                "status": "error",
                "data": [],
                "error": str(exc) or exc.__class__.__name__,
            }

    @abstractmethod
    async def search(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Основная логика: должен вернуть список нормализованных результатов."""
        raise NotImplementedError
