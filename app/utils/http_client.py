"""Единый асинхронный HTTP-клиент: браузерные заголовки, UA-ротация, retry.

Все модули через него: обходит простые блокировки (403 Cloudflare, 429, 503),
не вешает всё на таймаут, не застревает в retry.
"""

import logging
import random
from typing import Any, Dict, Optional

import httpx
from loguru import logger
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config import get_settings

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
]

_client: Optional[httpx.AsyncClient] = None


def random_headers() -> Dict[str, str]:
    """Псевдо-браузерный заголовок на каждый запрос."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Fetch-Dest": random.choice(["document", "empty", "image", "script"]),
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
        "Cache-Control": "max-age=0",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
    }


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        settings = get_settings()
        _client = httpx.AsyncClient(
            timeout=settings.request_timeout,
            headers=random_headers(),
            proxy=settings.proxy_url or None,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        finally:
            _client = None


def _is_retryable_status(code: int) -> bool:
    return code in (429, 500, 502, 503, 504)


@retry(
    retry=(
        retry_if_exception_type(httpx.TransportError)
        | retry_if_exception_type(httpx.HTTPStatusError)
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=6),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
async def request(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    """Выполняет запрос; повторяет при 429/5xx и TransportError.
    Модули получают обычный Response (могут проверять status_code).
    """
    headers = kwargs.pop("headers", {})
    merged = {**random_headers(), **headers}
    resp = await client.request(method, url, headers=merged, **kwargs)
    if _is_retryable_status(resp.status_code):
        raise httpx.HTTPStatusError(
            f"HTTP {resp.status_code} for {url}",
            request=resp.request,
            response=resp,
        )
    return resp


async def get(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    return await request(client, "GET", url, **kwargs)


async def post(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    return await request(client, "POST", url, **kwargs)


async def fetch_text(url: str, **kwargs) -> Optional[str]:
    """Удобная обёртка: получить текст или None при любой ошибке."""
    try:
        resp = await request(get_client(), "GET", url, follow_redirects=True, timeout=10.0, **kwargs)
        return resp.text
    except Exception as exc:
        logger.debug(f"fetch_text failed for {url}: {exc}")
        return None
