"""PhotoModule — обратный поиск по фото.

Источники:
1. Yandex Images (https://yandex.ru/images/) — поиск по public URL
   (GET https://yandex.ru/images/search?cbir_mode=send&url=...) и по файлу
   (POST multipart на https://yandex.ru/images/search?cbir_mode=send).
2. TinEye — пубlic multipart-flow (best-effort; без официального ключа).
3. Search4faces — best-effort парсинг страницы по фоту.

Вывод: ссылки на страницы с аналогичными изображениями + совпадения.
"""

import hashlib
import re
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from app.modules.base import BaseModule
from app.utils import normalizer
from app.utils.http_client import get as http_get
from app.utils.http_client import get_client, post as http_post


def _save_file(value: str) -> Optional[Path]:
    """Сохраняет base64/URL/data-URI/путь в файл и возвращает путь."""
    value = value.strip()
    try:
        if value.startswith("data:"):
            import base64
            header, _, data = value.partition(",")
            ext = "bin"
            m = re.search(r"data:image/(\w+)", header)
            if m:
                ext = m.group(1)
            path = Path(tempfile.gettempdir()) / f"vespera_photo_{hashlib.md5(value.encode()).hexdigest()[:12]}.{ext}"
            path.write_bytes(base64.b64decode(data))
            return path
        p = Path(value)
        if p.is_file():
            return p
    except Exception:
        pass
    return None


async def _yandex_by_url(client, url: str) -> List[Dict[str, Any]]:
    try:
        resp = await http_get(
            client,
            "https://yandex.ru/images/search",
            params={"cbir_mode": "send", "url": url},
            timeout=20.0,
            follow_redirects=True,
        )
        text = resp.text or ""
        links = re.findall(r'href=["\'](https://yandex\.ru/images/[^"\']+)["\']', text)
        out = [normalizer.norm(source="Yandex Images", url=u, title="Похожее изображение", confidence="low") for u in dict.fromkeys(links)[:5]]
        return out
    except Exception as exc:
        logger.warning(f"[photo_module] yandex by url failed: {exc}")
        return []


async def _yandex_by_file(client, file_path: Path) -> List[Dict[str, Any]]:
    """Загрузка локального файла на yandex — best-effort (JS-тяжёлой формы нет)."""
    try:
        with open(file_path, "rb") as f:
            resp = await http_post(
                client,
                "https://yandex.ru/images/search",
                params={"cbir_mode": "send"},
                files={"file": (file_path.name, f, "image/*")},
                timeout=30.0,
            )
        if resp.status_code in (200, 201, 202):
            return [
                normalizer.norm(
                    source="Yandex Images",
                    url="https://yandex.ru/images/",
                    title=f"Обратный поиск по файлу {file_path.name}",
                    confidence="low",
                )
            ]
    except Exception as exc:
        logger.warning(f"[photo_module] yandex by file failed: {exc}")
    return []


async def _tineye(client, file_path: Path) -> List[Dict[str, Any]]:
    """TinEye public multipart flow — best-effort."""
    try:
        with open(file_path, "rb") as f:
            resp = await http_post(
                client,
                "https://tineye.com/multipart/upload",
                data={"best": "yes", "size_check": "0", "search_limit": "8"},
                files={"files": (file_path.name, f, "image/*")},
                timeout=30.0,
            )
        if resp.status_code != 200:
            return []
        links = re.findall(r'["\']?(https://tineye\.com/[^"\']+)["\']?', resp.text or "")
        return [
            normalizer.norm(source="TinEye", url=u, title="Совпадения на TinEye", confidence="low")
            for u in dict.fromkeys(links)[:5]
        ]
    except Exception as exc:
        logger.warning(f"[photo_module] tineye failed: {exc}")
    return []


async def _search4faces(client, file_path: Path) -> List[Dict[str, Any]]:
    try:
        with open(file_path, "rb") as f:
            resp = await http_post(
                client,
                "https://search4faces.com/vk/",
                files={"file": (file_path.name, f, "image/*")},
                timeout=30.0,
            )
        text = resp.text or ""
        if resp.status_code == 200:
            links = re.findall(r'href=["\'](https://(?:vk\.com|faceapp|pinterest)[^"\']+)["\']', text)
            if links:
                return [
                    normalizer.norm(source="Search4faces", url=u, title="Совпадения по лицу", confidence="low")
                    for u in dict.fromkeys(links)[:5]
                ]
    except Exception as exc:
        logger.warning(f"[photo_module] search4faces failed: {exc}")
    return []


class PhotoModule(BaseModule):
    name = "photo_module"
    supported_inputs = ["photo", "file"]
    timeout = 60.0

    def domain(self, query=None):
        return "photo_module"

    async def search(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        value = query["value"]
        # photo как URL или base64
        if value.startswith(("http://", "https://")):
            return await self._search_url(value)
        file_path = _save_file(value)
        if file_path is None:
            return []
        client = get_client()
        results: List[Dict[str, Any]] = []
        results.extend(await _yandex_by_file(client, file_path))
        results.extend(await _tineye(client, file_path))
        results.extend(await _search4faces(client, file_path))
        return results

    async def _search_url(self, url: str) -> List[Dict[str, Any]]:
        client = get_client()
        results: List[Dict[str, Any]] = []
        results.extend(await _yandex_by_url(client, url))
        return results
