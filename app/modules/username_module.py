"""UsernameModule — параллельная проверка ника по WhatsMyName dataset + прямые проверки.

Стратегия отказоустойчивости:
- При блокировке (403/503/429) возвращаем не ошибку, а карточку со ссылкой
  для ручной проверки на самом сайте (fallback).
- Параллельные запросы (Semaphore) — 691 проверок быстро.
- Сначала "найден" (подтверждённый), потом "ручная проверка".
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from app.modules.base import BaseModule
from app.utils import normalizer
from app.utils.http_client import get as http_get
from app.utils.http_client import get_client
from app.utils.validators import validate_username

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
WMN_DATA_FILE = DATA_DIR / "wmn-data.json"
CONCURRENT = 12
TIMEOUT = 10.0


def load_wmn_sites() -> List[Dict[str, Any]]:
    try:
        raw = json.loads(WMN_DATA_FILE.read_text(encoding="utf-8"))
        return [
            s for s in raw.get("sites", [])
            if s.get("valid") is not False and s.get("uri_check")
        ]
    except Exception as exc:
        logger.warning(f"[username_module] wmn data load failed: {exc}")
        return []


def _manual_fallback(site: Dict[str, Any], username: str) -> Dict[str, Any]:
    """Ссылка для ручной проверки, если сайт заблокировал нас."""
    return normalizer.norm(
        source=f"{site.get('name', site.get('uri_check', '?'))} — ручная проверка",
        url=site["uri_check"].replace("{account}", username),
        title=f"{site.get('name', '')}: {username} (открыть страницу)",
        snippet=f"Сайт не отдаёт данные автоматически — проверьте вручную.",
        confidence="info",
    )


async def _check_site(client, site: Dict[str, Any], username: str) -> Optional[Dict[str, Any]]:
    url = site["uri_check"].replace("{account}", username)
    e_code = site.get("e_code", 200)
    e_string = site.get("e_string", "")
    m_string = site.get("m_string", "")
    m_code = site.get("m_code", 404)
    try:
        resp = await http_get(client, url, timeout=TIMEOUT, follow_redirects=True)
    except Exception as exc:
        logger.debug(f"[username_module] {site.get('name')}: {exc}")
        return None
    text = resp.text or ""
    e_hit = resp.status_code == e_code and (not e_string or e_string in text)
    m_hit = (
        m_code is not None
        and resp.status_code == m_code
        and (not m_string or m_string in text)
    )
    if e_hit and not m_hit:
        return normalizer.norm(
            source=f"WhatsMyName: {site.get('name', '')}",
            url=url,
            title=f"{site.get('name', '')}: ник «{username}»",
            snippet=f"Найден профиль по нику «{username}» (e_code={e_code}).",
            confidence="medium",
            verified=True,
            extra={"site": site.get("name"), "e_code": e_code, "wmn_cat": site.get("cat")},
        )
    if resp.status_code in (403, 429, 503):
        return _manual_fallback(site, username)
    return None


DIRECT_SITES: List[tuple] = [
    ("GitHub", "https://github.com/{u}"),
    ("VK", "https://vk.com/{u}"),
    ("Telegram", "https://t.me/{u}"),
    ("Twitter/X", "https://twitter.com/{u}"),
    ("Threads", "https://threads.net/@{u}"),
    ("Mastodon", "https://mastodon.social/@{u}"),
    ("Steam", "https://steamcommunity.com/id/{u}"),
    ("GitLab", "https://gitlab.com/{u}"),
    ("Keybase", "https://keybase.io/{u}"),
    ("Dribbble", "https://dribbble.com/{u}"),
    ("Spotify", "https://open.spotify.com/user/{u}"),
    ("Substack", "https://substack.com/@{u}"),
    ("Medium", "https://medium.com/@{u}"),
    ("Obsidian", "https://publish.obsidian.md/{u}"),
]


async def _check_direct(client, username: str) -> List[Dict[str, Any]]:
    async def one(site: str, tmpl: str) -> Optional[Dict[str, Any]]:
        url = tmpl.format(u=username)
        try:
            resp = await http_get(client, url, timeout=TIMEOUT, follow_redirects=True)
            if resp.status_code in (200, 201):
                return normalizer.norm(
                    source=site,
                    url=url,
                    title=f"{site}: ник «{username}»",
                    snippet=f"Публичный профиль найден.",
                    confidence="medium",
                    verified=True,
                )
            if resp.status_code == 404:
                return None
        except Exception:
            pass
        return normalizer.norm(
            source=f"{site} — ручная проверка",
            url=url,
            title=f"{site}: {username} (открыть страницу)",
            snippet="Прямой проверки не получилось — откройте ссылку вручную.",
            confidence="info",
        )

    return [r for r in await asyncio.gather(*(one(s, t) for s, t in DIRECT_SITES)) if r]


class UsernameModule(BaseModule):
    name = "username_module"
    supported_inputs = ["username"]
    timeout = 600.0  # 691+ параллельных проверок + возможные таймауты — запас

    async def search(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        username = validate_username(query["value"])
        client = get_client()
        sites = load_wmn_sites()
        logger.info(f"[username_module] checking {username!r} against {len(sites)} sites + {len(DIRECT_SITES)} direct")

        sem = asyncio.Semaphore(CONCURRENT)
        total = len(sites)
        done_count = 0

        async def worker(site):
            nonlocal done_count
            async with sem:
                res = await _check_site(client, site, username)
                done_count += 1
                if done_count % 20 == 0 or done_count == total:
                    self.progress.append(f"{done_count}/{total} проверено")
                return res

        wmn_results = await asyncio.gather(*(worker(s) for s in sites))
        direct_results = await _check_direct(client, username)

        merged: Dict[str, Dict[str, Any]] = {}
        for item in [r for r in wmn_results if r] + [r for r in direct_results if r]:
            key = item["url"] or item["title"]
            existing = merged.get(key)
            if existing is None or (existing["confidence"] == "info" and item["confidence"] != "info"):
                merged[key] = item
        logger.info(f"[username_module] done: {len(merged)} results")
        return list(merged.values())
