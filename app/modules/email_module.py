"""EmailModule — поиск по email: HIBP, leaked.directory, Gravatar, MX, доп. источники.

graceful degradation: ключи не заданы -> источник пропускается с warning,
но остальные источники продолжают работать.
"""

import asyncio
import hashlib
import re
from typing import Any, Dict, List, Optional

from loguru import logger

from app.config import get_settings
from app.modules.base import BaseModule
from app.utils import normalizer
from app.utils.http_client import fetch_text, get as http_get, get_client
from app.utils.validators import validate_email


def _domain_of(email: str) -> str:
    return email.strip().rsplit("@", 1)[-1].lower()


def _norm_hibp(payload: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for item in payload or []:
        breach = item.get("Name", "?")
        out.append(
            normalizer.norm(
                source=f"haveibeenpwned (утечка: {breach})",
                url="https://haveibeenpwned.com/",
                title=f"Email попал в утечку «{breach}»",
                snippet=f"Домен: {item.get('Domain', '')}; баз паролей: {item.get('PwnCount', 0)}",
                confidence="high",
                verified=True,
                extra={"domain": item.get("Domain"), "pwn_count": item.get("PwnCount")},
            )
        )
    return out


async def _hibp(client, email: str) -> List[Dict[str, Any]]:
    settings = get_settings()
    if not settings.hibp_api_key:
        logger.warning("[email_module] HIBP_API_KEY не задан — пропуск HaveIBeenPwned (добавьте в .env)")
        return []
    url = f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}"
    try:
        resp = await http_get(
            client, url, headers={"HaveIBeenPwned-API-Key": settings.hibp_api_key}, timeout=10.0
        )
        if resp.status_code == 200:
            return _norm_hibp(resp.json())
    except Exception as exc:
        logger.debug(f"[email_module] HIBP error: {exc}")
    return []


def _norm_leaked_directory(payload: Any) -> List[Dict[str, Any]]:
    items: List[str] = []
    if isinstance(payload, list):
        items = [i for i in payload if isinstance(i, str)]
    elif isinstance(payload, dict):
        # разные варианты форматов ответа
        for key in ("result", "leaks", "data", "breaches"):
            val = payload.get(key)
            if isinstance(val, list):
                items = [i for i in val if isinstance(i, str)]
                break
    out = []
    for leak in items[:5]:
        name = re.sub(r"[-_]", " ", leak)[:60]
        out.append(
            normalizer.norm(
                source="leaked.directory",
                url="https://leaked.directory/",
                title=f"Утечка: {name}",
                confidence="medium",
                verified=True,
            )
        )
    return out


async def _leaked_directory(client, email: str) -> List[Dict[str, Any]]:
    url = "https://leaked.directory/api/v1/search/emails"
    try:
        resp = await http_get(client, url, params={"email": email}, timeout=10.0)
        if resp.status_code == 200:
            return _norm_leaked_directory(resp.json())
    except Exception as exc:
        logger.debug(f"[email_module] leaked.directory error: {exc}")
    return []


async def _gravatar(email: str) -> List[Dict[str, Any]]:
    """Gravatar: MD5-хэш email -> профиль (если существует)."""
    try:
        md5 = hashlib.md5(email.encode("utf-8")).hexdigest()
        url = f"https://en.gravatar.com/{md5}"
        text = await fetch_text(url, timeout=10.0)
        if text and "<title>" in text:
            title = re.search(r"<title[^>]*>([^<]{3,80})", text)
            return [
                normalizer.norm(
                    source="Gravatar",
                    url=url,
                    title=(title.group(1).strip() or f"Профиль Gravatar (md5 {md5[:8]}...)") if title else f"Gravatar: {email}",
                    confidence="medium",
                    verified=True,
                )
            ]
    except Exception:
        pass
    return []


def _mx_records(domain: str) -> List[Dict[str, Any]]:
    try:
        import dns.resolver
    except ImportError:
        return []
    try:
        answers = dns.resolver.resolve(domain, "MX")
        return [
            normalizer.norm(
                source="dns.mx",
                url=None,
                title=f"MX-записи домена {domain}",
                snippet=", ".join(f"{r.exchange} (prio {r.preference})" for r in answers),
                confidence="high",
                verified=True,
                extra={"domain": domain},
            )
        ]
    except Exception as exc:
        logger.debug(f"[email_module] MX lookup failed for {domain}: {exc}")
    return []


class EmailModule(BaseModule):
    name = "email_module"
    supported_inputs = ["email"]
    timeout = 30.0

    def domain(self, query=None):
        value = (query or {}).get("value", "")
        return _domain_of(value) if value else "email_module"

    async def search(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        email = validate_email(query["value"])
        domain = _domain_of(email)
        client = get_client()
        results = await asyncio.gather(
            _hibp(client, email),
            _leaked_directory(client, email),
            _gravatar(email),
        )
        out = [r for part in results for r in part]
        out.extend(_mx_records(domain))
        return out
