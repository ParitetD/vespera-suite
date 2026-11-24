"""Единая схема нормализованного результата модуля."""

from typing import Any, Dict, Optional


def norm(
    source: str,
    url: Optional[str] = None,
    title: Optional[str] = None,
    snippet: Optional[str] = None,
    confidence: str = "low",
    verified: bool = False,
    extra: Optional[Dict[str, Any]] = None,
    type: str = "",
) -> Dict[str, Any]:
    """Приводит вывод модуля к схеме:

    {source, url, title, snippet, confidence, verified, extra, type}

    confidence: "high" | "medium" | "low" | "info".
    """
    return {
        "source": source,
        "url": url,
        "title": title,
        "snippet": snippet,
        "confidence": confidence,
        "verified": bool(verified),
        "extra": extra or {},
        "type": type,
    }
