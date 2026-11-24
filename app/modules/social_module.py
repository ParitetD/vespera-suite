"""SocialModule — поиск по ФИО/городу или username в соцсетях.

Источники:
1. VK API (users.search) — нужен VK_ACCESS_TOKEN (.env).
2. Яндекс People (people.yandex.ru) — best-effort парсинг.
3. Facebook (публичные страницы поиска) — best-effort.
4. Twitter/X advanced search (snscrape) — опционально, если установлен.

graceful degradation: без токена VK API источник пропускается с warning.
"""

import json
import re
import shutil
import subprocess
from typing import Any, Dict, List
from urllib.parse import urlencode

from loguru import logger

from app.config import get_settings
from app.modules.base import BaseModule
from app.utils import normalizer
from app.utils.http_client import get as http_get
from app.utils.http_client import get_client


def _linkify(text: str) -> str:
    """Вытаскивает URL из HTML-фрагментов для сниппетов."""
    return re.sub(r"<[^>]+>", " ", text)[:200].strip()


async def _vk_api(client, query: str, token: str) -> List[Dict[str, Any]]:
    try:
        resp = await http_get(
            client,
            "https://api.vk.com/method/users.search",
            params={
                "q": query,
                "count": 5,
                "fields": "id,first_name,last_name,photo_50,screen_name",
                "v": "5.131",
                "access_token": token,
            },
            timeout=15.0,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        out = []
        for user in data.get("response", {}).get("items", []):
            screen = user.get("screen_name") or user.get("id")
            out.append(
                normalizer.norm(
                    source="VK API",
                    url=f"https://vk.com/{screen}",
                    title=f"{user.get('first_name')} {user.get('last_name')}",
                    snippet=f"Профиль: https://vk.com/{screen}",
                    confidence="high",
                    verified=True,
                    extra={"id": user.get("id")},
                )
            )
        return out
    except Exception as exc:
        logger.warning(f"[social_module] VK API error: {exc}")
        return []


async def _yandex_people(client, query: str) -> List[Dict[str, Any]]:
    """Яндекс People — best-effort: собираем ссылки/имена из страницы."""
    try:
        resp = await http_get(
            client,
            "https://people.yandex.ru/",
            params={"q": query},
            timeout=15.0,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return []
        text = resp.text or ""
        # На странице есть ссылки на профили в виде people-name-... 
        links = re.findall(r'href=["\'](https://yandex\.ru/people[^"\']+)["\']', text)
        return [
            normalizer.norm(source="Яндекс People", url=u, title=f"Профиль: {u}", confidence="low")
            for u in dict.fromkeys(links)[:5]
        ]
    except Exception:
        return []


async def _facebook(client, query: str) -> List[Dict[str, Any]]:
    """Facebook ранжирует поиск по людям; парсим публичные ссылки."""
    try:
        resp = await http_get(
            client,
            "https://www.facebook.com/search/people/",
            params=urlencode({"q": query, "ref": "search_public"}).replace("%2B", "+"),
            timeout=15.0,
            follow_redirects=True,
        )
        text = resp.text or ""
        links = re.findall(r'href=["\'](https?://(?:www\.)?facebook\.com/(?:profile\.php\?id=|[^/\\?"]+)[^"\']*)["\']', text)
        seen, out = set(), []
        for u in links:
            u = re.sub(r"[?&]ref=[^&]+", "", u)
            if u in seen:
                continue
            seen.add(u)
            snippet = ""
            m = re.search(re.escape(u.split("?")[0]) + r'["\'][^>]*>([^<]{3,80})', text)
            if m:
                snippet = _linkify(m.group(1))
            out.append(
                normalizer.norm(
                    source="Facebook",
                    url=u,
                    title=u.split("/")[-1],
                    snippet=snippet,
                    confidence="low",
                )
            )
        return out[:5]
    except Exception:
        return []


def _snscrape_twitter(query: str) -> List[Dict[str, Any]]:
    """Twitter/X advanced search через snscrape (опционально)."""
    if not shutil.which("snscrape"):
        return []
    try:
        out = subprocess.run(
            ["snscrape", "--jsonl", f"twitter-search '{query}'"],
            capture_output=True, text=True, timeout=60,
        )
    except Exception:
        return []
    results = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        content = entry.get("content", "")
        username_m = re.search(r"@(\w{1,15})", content)
        if username_m:
            results.append(
                normalizer.norm(
                    source="Twitter/X (snscrape)",
                    url=f"https://twitter.com/{username_m.group(1)}",
                    title=f"@{username_m.group(1)}",
                    snippet=_linkify(content)[:200],
                    confidence="low",
                )
            )
    return results[:5]


class SocialModule(BaseModule):
    name = "social_module"
    supported_inputs = ["social", "fio"]
    timeout = 30.0

    def domain(self, query=None):
        return "social_module"

    async def search(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        query_text = " ".join(
            part for part in [query.get("fio"), query.get("city"), query.get("query"), query.get("value")] if part
        ).strip()
        if not query_text:
            return []
        settings = get_settings()
        client = get_client()
        results: List[Dict[str, Any]] = []
        results.extend(await _vk_api(client, query_text, settings.vk_access_token or "") if settings.vk_access_token else [])
        if not settings.vk_access_token:
            logger.warning("[social_module] VK_ACCESS_TOKEN не задан — пропуск VK API")
        results.extend(await _yandex_people(client, query_text))
        results.extend(await _facebook(client, query_text))
        results.extend(_snscrape_twitter(query_text))
        return results
