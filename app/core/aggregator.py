"""Aggregator — сбор результатов всех модулей в единый отчёт.

Отсортированный оболочкой:
{
  "id": uuid4, "timestamp": iso, "query": {"type", "value"},
  "results": {"username": [...], "email": [...], "phone": [...],
              "social": [...], "photo": [...], "metadata": [...]},
  "errors": [{"module", "error"}],
  "summary": {"total_found", "sources_used", "high_confidence"}
}
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.utils.normalizer import norm

RESULT_KEYS = ("username", "email", "phone", "social", "photo", "metadata")

# Поля, которые norm() принимает — защита от неожиданных ключей модулей
_NORM_KEYS = {"source", "url", "title", "snippet", "confidence", "verified", "extra", "type"}


def _clean_item(item: Any) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return norm(source=str(item))
    data = {k: v for k, v in item.items() if k in _NORM_KEYS}
    if "source" not in data:
        data["source"] = "unknown"
    return norm(**data)


def _dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for item in items:
        key = item.get("url") or item.get("title") or item.get("source")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _extract_key_info(query: Dict[str, Any], grouped: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Ключевые факты для верхнего блока отчёта (страна/оператор/MX/Gravatar и т.п.)."""
    qtype = query.get("type")
    items = grouped.get(qtype, []) if qtype in grouped else []
    out: List[Dict[str, Any]] = []
    if qtype == "phone":
        for it in items:
            if it.get("source") == "phonenumbers":
                extra = it.get("extra", {})
                out.append({
                    "title": f"Телефон: {extra.get('national_number', '')}",
                    "value": f"Страна {extra.get('country_name') or extra.get('country_code') or '?'}",
                    "carrier": extra.get("carrier") or "Неизвестно",
                    "line_type": extra.get("line_type") or "",
                    "valid": bool(extra.get("valid")),
                })
                break
    elif qtype == "email":
        for it in items:
            if it.get("source") == "dns.mx":
                out.append({
                    "title": f"MX-запись домена {it.get('extra', {}).get('domain', '')}",
                    "value": it.get("snippet", "") or it.get("title", ""),
                })
                break
        for it in items:
            if it.get("source", "").startswith("Gravatar") and len(out) < 3:
                out.append({"title": it.get("title", "Gravatar"), "value": it.get("url", "")})
    elif qtype == "username":
        for it in items[:3]:
            out.append({
                "title": it.get("title", ""),
                "value": it.get("url") or "",
                "confidence": it.get("confidence", ""),
            })
    return out[:4]


def _build_graph_data(query: Dict[str, Any], grouped: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Граф для Cytoscape: корень — запрос, узлы результатов по типам (dagre, LR)."""
    nodes = [{"data": {"id": "root", "label": query.get("value", ""), "type": "query"}}]
    edges = []
    for type_key, items in grouped.items():
        if not items:
            continue
        cat_id = f"cat_{type_key}"
        nodes.append({"data": {"id": cat_id, "label": type_key.upper(), "type": "category"}})
        edges.append({"data": {"source": "root", "target": cat_id}})
        for idx, item in enumerate(items[:20]):
            node_id = f"{type_key}_{idx}_{hash(item.get('url') or item.get('title') or '') % 100000}"
            nodes.append({
                "data": {
                    "id": node_id,
                    "label": (item.get("title") or item.get("source") or type_key)[:40],
                    "type": "profile",
                    "url": item.get("url"),
                    "confidence": item.get("confidence"),
                }
            })
            edges.append({"data": {"source": cat_id, "target": node_id}})
    return {"nodes": nodes, "edges": edges}


class Aggregator:
    def aggregate(self, query: Dict[str, Any], module_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        grouped: Dict[str, List[Dict[str, Any]]] = {key: [] for key in RESULT_KEYS}
        errors: List[Dict[str, Any]] = []
        key = query.get("type") if query.get("type") in grouped else "social"
        for res in module_results:
            if res.get("status") == "ok":
                for item in res.get("data", []):
                    grouped[key].append(_clean_item(item))
            elif res.get("status") == "error":
                errors.append({"module": res.get("module", "?"), "error": res.get("error") or "unknown"})
        grouped = {k: _dedupe(v) for k, v in grouped.items()}
        summary = {
            "total_found": sum(len(v) for v in grouped.values()),
            "sources_used": sum(1 for r in module_results if r.get("status") == "ok"),
            "high_confidence": [
                d.get("url") or d.get("title") or d.get("source")
                for v in grouped.values()
                for d in v
                if d.get("confidence") == "high"
            ],
        }
        return {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "query": {"type": query.get("type", ""), "value": query.get("value", "")},
            "key_info": _extract_key_info(query, grouped),
            "graph_data": _build_graph_data(query, grouped),
            "results": grouped,
            "errors": errors,
            "summary": summary,
        }
