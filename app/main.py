"""Точка входа: FastAPI + WebSocket-терминал (PTY) + AI Copilot."""

import asyncio
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import fcntl
import struct
import termios

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles с заголовками no-cache — чтобы браузер всегда перезагружал файлы после обновлений."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

from ai_helper import TerminalRing, ai_stream, build_context, read_log_tail
from app.api.routes import router, search_ws
from app.config import BASE_DIR, STATIC_DIR, get_settings
from app.db.session import init_db
from app.utils.http_client import close_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_client()


def create_app() -> FastAPI:
    settings = get_settings()

    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)
    logger.add(log_dir / "app.log", rotation="20 MB", level="DEBUG", enqueue=True)

    init_db()

    app = FastAPI(
        title=settings.title,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.websocket("/ws/search")(search_ws)

    # ---------- WebSocket: встроенный терминал (PTY) ----------
    terminal_ring = TerminalRing()

    @app.websocket("/ws/terminal")
    async def terminal_ws(websocket: WebSocket):
        """Интерактивный терминал поверх WebSocket: держит сессию shell в PTY."""
        await websocket.accept()
        if sys.platform == "win32":
            await websocket.send_json(
                {"type": "error", "message": "Терминал недоступен: Windows-сервер, используйте Linux/macOS"}
            )
            return

        import pty

        shell = os.environ.get("SHELL") or "/bin/bash"
        if not Path(shell).exists():
            shell = "/bin/bash"

        master_fd, slave_fd = pty.openpty()
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))

        try:
            proc = subprocess.Popen(
                [shell, "-i"],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                start_new_session=True,
            )
        except Exception as exc:
            os.close(master_fd)
            os.close(slave_fd)
            await websocket.send_json({"type": "error", "message": f"Ошибка запуска оболочки: {exc}"})
            return
        os.close(slave_fd)

        loop = asyncio.get_event_loop()
        stop = asyncio.Event()

        async def pump_pty():
            while not stop.is_set():
                try:
                    data = await loop.run_in_executor(None, os.read, master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                terminal_ring.add(data.decode("utf-8", errors="replace"))
                try:
                    await websocket.send_bytes(data)
                except Exception:
                    break

        async def pump_ws():
            try:
                while True:
                    data = await websocket.receive_text()
                    try:
                        os.write(master_fd, data.encode("utf-8", errors="replace"))
                    except OSError:
                        break
            except (WebSocketDisconnect, asyncio.CancelledError):
                pass

        reader = asyncio.create_task(pump_pty())
        writer = asyncio.create_task(pump_ws())
        done, pending = await asyncio.wait(
            [reader, writer], return_when=asyncio.FIRST_COMPLETED
        )
        stop.set()
        for t in (reader, writer):
            t.cancel()
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
        os.close(master_fd)

    # ---------- WebSocket: AI Copilot ----------
    @app.websocket("/ws/ai-chat")
    async def ai_chat_ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json(
            {
                "type": "welcome",
                "message": "AI Copilot Vespera: опишите проблему, и я проанализирую логи и предложу решение.",
            }
        )
        try:
            while True:
                data = await websocket.receive_json()
                if not isinstance(data, dict) or data.get("type") != "chat":
                    continue
                user_q = str(data.get("message", "")).strip()
                if not user_q:
                    continue
                await websocket.send_json({"type": "chunk", "text": f"\n🧠 Анализирую логи...\n\n"})
                log_lines = read_log_tail(120)
                context = build_context(log_lines, terminal_ring.get_tail(200), user_q)
                async for chunk in ai_stream(context):
                    await websocket.send_json({"type": "chunk", "text": chunk})
                await websocket.send_json({"type": "done"})
        except WebSocketDisconnect:
            pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.opt(exception=True).error(f"[ai_chat_ws] error: {exc}")
            try:
                await websocket.send_json({"type": "error", "message": str(exc)})
            except Exception:
                pass

    # ---------- Статика ----------
    if STATIC_DIR.exists():
        app.mount("/", NoCacheStaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app


app = create_app()
