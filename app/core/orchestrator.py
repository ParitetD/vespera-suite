"""Orchestrator — главный мозг: фильтр модулей → параллельный запуск → агрегация.

Конфликт модулей исключён:
- BaseModule.safe_search изолирует отказ одного модуля от остальных;
- RateLimiter — общий per-domain для всех модулей;
- единый httpx.AsyncClient — connection pooling и ротация UA.

Все модули запускаются через asyncio.gather(return_exceptions=True);
падение одного модуля не ломает остальные.
"""

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger

from app.config import get_settings
from app.core.aggregator import Aggregator
from app.core.rate_limiter import RateLimiter
from app.modules.email_module import EmailModule
from app.modules.metadata_module import MetadataModule
from app.modules.phone_module import PhoneModule
from app.modules.photo_module import PhotoModule
from app.modules.social_module import SocialModule
from app.modules.username_module import UsernameModule

LogCallback = Optional[Callable[[str, str, Optional[str]], Awaitable[None]]]

# Общий RateLimiter на весь процесс: Orchestrator создаётся на каждый запрос,
# поэтому лимитеры на уровне модуля обнулялись каждый раз.
_shared_limiter = RateLimiter(get_settings().rate_limit_default)


def get_modules(limiter: Optional[RateLimiter] = None) -> List:
    """Все модули приложения."""
    return [
        UsernameModule(limiter),
        EmailModule(limiter),
        PhoneModule(limiter),
        SocialModule(limiter),
        PhotoModule(limiter),
        MetadataModule(limiter),
    ]


class Orchestrator:
    def __init__(self, modules: Optional[List] = None, limiter: Optional[RateLimiter] = None):
        self.limiter = limiter or _shared_limiter
        self.modules = modules if modules is not None else get_modules(self.limiter)
        self.aggregator = Aggregator()

    async def run(self, query: Dict[str, Any], log: LogCallback = None) -> Dict[str, Any]:
        async def _run_one(module):
            try:
                if log:
                    await log(module.name, "start")
                fut = asyncio.ensure_future(module.safe_search(query))
                # живые прогресс-сообщения модуля (поллинг — минимальный, ненагруженный реализм)
                while not fut.done():
                    if log:
                        prog = getattr(module, "progress", [])
                        for p in prog[module._progress_sent:]:
                            await log(module.name, "progress", p)
                        module._progress_sent = len(prog)
                    await asyncio.sleep(0.5)
                result = fut.result()
                if log:
                    await log(module.name, result["status"], f"{len(result['data'])} результатов" if result["data"] else None)
                return result
            except Exception as exc:  # броня: safe_search должен перехватить всё, но на всякий случай
                logger.opt(exception=True).error(f"[orchestrator] {module.name} crashed: {exc}")
                return {"module": module.name, "status": "error", "data": [], "error": str(exc)}

        allowed = query.get("modules")
        modules = [
            m
            for m in self.modules
            if (query.get("type") in m.supported_inputs) and (not allowed or m.name in allowed)
        ]
        results = await asyncio.gather(*[_run_one(m) for m in modules])
        try:
            return self.aggregator.aggregate(query, results)
        except Exception as exc:  # агрегатор не должен ломать запрос
            logger.opt(exception=True).error(f"[orchestrator] aggregate failed: {exc}")
            envelope = self.aggregator.aggregate(query, [])
            envelope["errors"].append({"module": "orchestrator", "error": f"aggregate failed: {exc}"})
            return envelope
