"""REST API + SSE-поток логов."""

import asyncio
import json
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.api.schemas import SearchRequest
from app.core.orchestrator import Orchestrator, get_modules
from app.db.session import Database
router = APIRouter()
_db = Database()
HISTORY_LIMIT_CAP = 500


@router.get("/api/health")
async def health():
    return {"status": "ok", "modules": [m.name for m in get_modules()]}


@router.get("/api/modules")
async def modules():
    """Список доступных модулей: имя + поддерживаемые типы запросов."""
    return {
        "modules": [
            {"name": m.name, "supported_inputs": list(m.supported_inputs)} for m in get_modules()
        ]
    }


@router.post("/api/search")
async def search_post(req: SearchRequest):
    query = {"type": req.type, "value": req.value.strip(), "modules": req.modules}
    cached = _db.get_cached(query)
    if cached is not None:
        return cached
    result = await Orchestrator().run(query)
    _db.set_cached(query, result)
    _db.add_history(result)
    return result


def _parse_modules(modules) -> Optional[List[str]]:
    """Принимает и строку (SSE query param), и список (WebSocket)."""
    if not modules:
        return None
    if isinstance(modules, str):
        modules = modules.split(",")
    return [m for m in modules if m]


def _empty_envelope(query: dict) -> dict:
    """Fallback-конверт ошибки (консистентный с Aggregator)."""
    return {
        "id": None,
        "timestamp": "",
        "query": {"type": query.get("type", ""), "value": query.get("value", "")},
        "results": {"username": [], "email": [], "phone": [], "social": [], "photo": [], "metadata": []},
        "errors": [],
        "summary": {"total_found": 0, "sources_used": 0, "high_confidence": []},
    }


async def run_search(query: dict, log=None) -> dict:
    """Общая логика поиска: кэш → оркестратор → сохранение (SSE и WS вызывают это)."""
    cached = _db.get_cached(query)
    if cached is not None:
        if log:
            await log("cache", "ok", "ответ из кэша")
        return cached
    result = await Orchestrator().run(query, log=log)
    _db.set_cached(query, result)
    _db.add_history(result)
    return result


async def search_ws(websocket: WebSocket) -> None:
    """WebSocket /ws/search: реальный поиск с live-логами.

    Протокол:
      клиент → {"type": "...", "value": "...", "modules": [...] (опц.)}
      сервер  → {"type": "log"|"result"|"error", ...}
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            if not isinstance(data, dict) or not data.get("type"):
                await websocket.send_json({"type": "error", "message": "Некорректный запрос"})
                continue
            try:
                req = SearchRequest(
                    type=data["type"],
                    value=data.get("value", ""),
                    modules=_parse_modules(data.get("modules")),
                )
            except ValidationError as exc:
                detail = (exc.errors()[0].get("msg") or "invalid request") if exc.errors() else "invalid request"
                await websocket.send_json({"type": "error", "message": detail})
                continue
            query = {"type": req.type, "value": req.value, "modules": req.modules}

            queue: asyncio.Queue = asyncio.Queue()

            async def log(module: str, status: str, detail: Optional[str] = None) -> None:
                await queue.put(json.dumps(
                    {"type": "log", "module": module, "status": status, "detail": detail},
                    ensure_ascii=False,
                ))

            async def runner() -> None:
                try:
                    result = await run_search(query, log)
                except Exception as exc:
                    result = _empty_envelope(query)
                    result["errors"].append({"module": "orchestrator", "error": str(exc)})
                await queue.put(json.dumps({"type": "result", "result": result}, ensure_ascii=False))
                await queue.put(None)

            task = asyncio.create_task(runner())
            while True:
                item = await queue.get()
                if item is None:
                    break
                await websocket.send_text(item)
            await task
    except WebSocketDisconnect:
        pass


@router.get("/api/search")
async def search_sse(type: str, value: str, modules: Optional[str] = None):
    """SSE: поток событий с логами времени {'type':'log',...},
    в конце — {'type':'result','result':...}."""
    # валидация через SearchRequest — ошибка клиента возвращается как 422
    try:
        validated = SearchRequest(type=type, value=value, modules=_parse_modules(modules))
    except ValidationError as exc:
        detail = (exc.errors()[0].get("msg") or "invalid request") if exc.errors() else "invalid request"
        raise HTTPException(status_code=422, detail=detail) from exc
    modules_list = validated.modules

    queue: asyncio.Queue = asyncio.Queue()

    async def log(module: str, status: str, detail: Optional[str] = None) -> None:
        event = {"type": "log", "module": module, "status": status, "detail": detail, "ts": time.time()}
        await queue.put(f"data: {json.dumps(event, ensure_ascii=False)}\n\n")

    async def run() -> None:
        query = {"type": type, "value": value.strip(), "modules": modules_list}
        try:
            result = await run_search(query, log)
        except Exception as exc:
            result = _empty_envelope(query)
            result["errors"].append({"module": "orchestrator", "error": str(exc)})
        await queue.put(f"data: {json.dumps({'type': 'result', 'result': result}, ensure_ascii=False)}\n\n")
        await queue.put(None)

    async def gen():
        task = asyncio.create_task(run())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/history")
async def history(limit: int = 50):
    # отрицательный limit в SQLite означает «без лимита» — нормализуем
    limit = max(0, min(limit, HISTORY_LIMIT_CAP))
    return {"items": _db.history(limit=limit)}


@router.get("/api/history/{history_id}")
async def history_detail(history_id: str):
    row = _db.get_history(history_id)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    return row


@router.delete("/api/history")
async def history_clear():
    return {"deleted": _db.clear_history()}
