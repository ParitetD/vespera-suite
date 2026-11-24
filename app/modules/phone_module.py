"""PhoneModule — поиск по телефону.

Источники:
- phonenumbers: точная валидация + страна + оператор + тип линии (публичная библиотека).
- Ручные ссылки для поиска (WhatsApp/Telegram/Truecaller/numverify/doska-org) —
  работают всегда, т.к. их API исторически закрыты от автоматизации.
- doska-org.ru — парсинг по параметру search.
"""

from typing import Any, Dict, List, Optional

import phonenumbers as pn

from app.modules.base import BaseModule
from app.utils import normalizer
from app.utils.http_client import get as http_get
from app.utils.http_client import get_client
from app.utils.validators import validate_phone

MANUAL_LINKS = [
    ("WhatsApp", "https://wa.me/{n}"),
    ("Telegram", "https://t.me/{n}"),
    ("Truecaller", "https://www.truecaller.com/search?q={n}"),
    ("numverify", "https://numverify.com/"),
    ("doska-org.ru", "https://doska-org.ru/search?search={n}"),
]


def _norm_metadata(e164: str) -> Dict[str, Any]:
    parsed = pn.parse(e164, "RU")
    country = parsed.country_code
    carrier = ""
    try:
        carrier = pn.carrier(parsed) or ""
    except Exception:
        pass
    return {
        "country_code": country,
        "country_name": pn.region_code_for_number(parsed) or "",
        "national_number": parsed.national_number,
        "line_type": str(pn.number_type(parsed)),
        "valid": pn.is_valid_number(parsed),
        "carrier": carrier,
    }


async def _doska_search(client, e164: str) -> List[Dict[str, Any]]:
    try:
        resp = await http_get(client, "https://doska-org.ru/search", params={"search": e164}, timeout=10.0, follow_redirects=True)
        if resp.status_code == 200 and e164[1:] in (resp.text or ""):
            return [normalizer.norm(
                source="doska-org.ru",
                url="https://doska-org.ru/search?search=" + e164,
                title=f"Объявления по номеру {e164}",
                confidence="medium",
                verified=True,
            )]
    except Exception:
        pass
    return []


class PhoneModule(BaseModule):
    name = "phone_module"
    supported_inputs = ["phone"]
    timeout = 30.0

    def domain(self, query=None):
        return "phone_module"

    async def search(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        e164 = validate_phone(query["value"])
        meta = _norm_metadata(e164)
        out: List[Dict[str, Any]] = []
        out.append(
            normalizer.norm(
                source="phonenumbers",
                url=None,
                title=f"{pn.format_number(pn.parse(e164, 'RU'), pn.PhoneNumberFormat.INTERNATIONAL)} — {meta['line_type']}",
                snippet=f"Страна: {meta['country_name']}; Оператор: {meta['carrier'] or 'неизвестно'}; Валиден: {meta['valid']}",
                confidence="high",
                verified=meta["valid"],
                extra=meta,
            )
        )
        client = get_client()
        out.extend(await _doska_search(client, e164))
        # ручные ссылки — всегда в выдаче как ссылки для проверки
        digits = e164.lstrip("+")
        for name, tmpl in MANUAL_LINKS:
            out.append(
                normalizer.norm(
                    source=f"{name} — проверить вручную",
                    url=tmpl.format(n=digits),
                    title=f"{name}: {digits}",
                    snippet="Автоматизированный поиск недоступен — откройте ссылку.",
                    confidence="info",
                )
            )
        return out
