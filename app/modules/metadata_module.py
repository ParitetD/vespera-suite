"""MetadataModule — извлечение метаданных из файла.

Источники:
1. ExifTool (system binary, `exiftool -j`) — полный дамп метаданных.
2. Pillow (PIL) — fallback: EXIF JPEG/PNG/WEBP/TIFF + magic.
3. python-docx — автор/создание/изменение DOCX.
4. PyPDF2 (опц.) — метаданные PDF.

Вывод: список нормализованных результатов с extra=«все метаданные».
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from app.modules.base import BaseModule
from app.utils import normalizer


def _norm_exiftool(file_path: Path, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for item in data:
        if isinstance(item, dict) and item:
            tags = {k: v for k, v in item.items() if v not in (None, "", "None")}
            out.append(
                normalizer.norm(
                    source="exiftool",
                    url=None,
                    title=f"{file_path.name} — {tags.get('Model', tags.get('Make', ''))} {tags.get('DateTimeOriginal', '')}".strip(),
                    snippet=json.dumps(tags, ensure_ascii=False)[:400],
                    confidence="high",
                    verified=True,
                    extra=tags,
                )
            )
    return out


def _exiftool(file_path: Path) -> List[Dict[str, Any]]:
    if not shutil.which("exiftool"):
        logger.warning("[metadata_module] exiftool не найден (apt install exiftool) — пропуск")
        return []
    try:
        out = subprocess.run(
            ["exiftool", "-j", "-a", "-G1", "-L", str(file_path)],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return []
        data = json.loads(out.stdout)
        if isinstance(data, list) and data:
            return _norm_exiftool(file_path, data)
    except Exception as exc:
        logger.warning(f"[metadata_module] exiftool failed: {exc}")
    return []


def _pillow(file_path: Path) -> List[Dict[str, Any]]:
    try:
        from PIL import Image
    except ImportError:
        return []
    try:
        with Image.open(file_path) as im:
            exif = im.getexif()
            tags = {k: v for k, v in exif.items() if v not in (None, "")}
            if not tags:
                tags = dict(im.info)
            if not tags:
                return []
            return [
                normalizer.norm(
                    source="pillow",
                    url=None,
                    title=f"{file_path.name} — {im.format or ''} {tags.get('Exif', tags.get('DateTime', ''))}",
                    extra=tags,
                    confidence="medium",
                )
            ]
    except Exception:
        return []


def _docx(file_path: Path) -> List[Dict[str, Any]]:
    """DOCX core.xml: автор, даты создания/изменения, заголовок документа."""
    import xml.etree.ElementTree as ET
    import zipfile

    NS = "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}"
    try:
        with zipfile.ZipFile(file_path) as z:
            xml_data = z.read("docProps/core.xml")
        root = ET.fromstring(xml_data)
        props = {}
        for tag in ("title", "subject", "creator", "lastModifiedBy", "created", "modified", "lastPrinted"):
            el = root.find(f"{NS}{tag}")
            if el is not None and el.text:
                props[tag] = el.text
        if not props:
            return []
        return [
            normalizer.norm(
                source="python-docx (core.xml)",
                url=None,
                title=f"{file_path.name} — {props.get('creator', '')}",
                extra=props,
                confidence="high",
                verified=True,
            )
        ]
    except Exception:
        return []


def _pdf(file_path: Path) -> List[Dict[str, Any]]:
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        return []
    try:
        reader = PdfReader(str(file_path))
        meta = reader.metadata or {}
        props = {k: v for k, v in meta.items() if v}
        if not props:
            return []
        return [
            normalizer.norm(
                source="PyPDF2",
                url=None,
                title=f"{file_path.name} — {props.get('/Producer', props.get('/Creator', ''))}",
                extra=props,
                confidence="high",
                verified=True,
            )
        ]
    except Exception:
        return []


def _is_zip_with(file_path: Path, member: str) -> bool:
    import zipfile

    try:
        with zipfile.ZipFile(file_path) as z:
            return member in z.namelist()
    except Exception:
        return False


class MetadataModule(BaseModule):
    name = "metadata_module"
    supported_inputs = ["metadata", "file"]
    timeout = 30.0

    async def search(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        from app.modules.photo_module import _save_file

        file_path = _save_file(query["value"])
        if file_path is None or not file_path.is_file():
            return []
        ext = file_path.suffix.lower()
        results: List[Dict[str, Any]] = []
        results.extend(_exiftool(file_path))
        results.extend(_pillow(file_path))
        if ext in (".docx",) and _is_zip_with(file_path, "docProps/core.xml"):
            results.extend(_docx(file_path))
        if ext in (".pdf",):
            results.extend(_pdf(file_path))
        return results
