"""Подключение к SQLite через SQLAlchemy."""

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db.models import Base, RequestCache

# Результаты поиска динамичны: повтор за минуту полезен, за час и дольше — уже нет.
CACHE_TTL_SECONDS = 600


def init_db() -> None:
    settings = get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{settings.db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)


def _query_hash(query: Dict[str, Any]) -> str:
    raw = f"{query.get('type', '')}:{query.get('value', '')}:{sorted((query.get('modules') or []))}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Database:
    """Минимальный слой доступа к БД: история + простой кэш запросов."""

    def __init__(self):
        self._engine = create_engine(f"sqlite:///{get_settings().db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine)

    # --- history ---
    def add_history(self, result: Dict[str, Any]) -> None:
        from app.db.models import SearchHistory

        session = self._Session()
        try:
            session.add(
                SearchHistory(
                    id=result.get("id") or uuid.uuid4().hex,
                    type=result.get("query", {}).get("type", "") or "",
                    value=result.get("query", {}).get("value", "") or "",
                    result_json=json.dumps(result, ensure_ascii=False),
                )
            )
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    def history(self, limit: int = 50) -> List[Dict[str, Any]]:
        from app.db.models import SearchHistory

        session = self._Session()
        try:
            rows = session.query(SearchHistory).order_by(SearchHistory.created_at.desc()).limit(limit).all()
            items = []
            for r in rows:
                result = json.loads(r.result_json) if r.result_json else None
                items.append(
                    {
                        "id": r.id,
                        "type": r.type,
                        "value": r.value,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                        "result": result,
                        "total_found": (result or {}).get("summary", {}).get("total_found"),
                    }
                )
            return items
        finally:
            session.close()

    def get_history(self, history_id: str) -> Optional[Dict[str, Any]]:
        from app.db.models import SearchHistory

        session = self._Session()
        try:
            row = session.get(SearchHistory, history_id)
            if not row:
                return None
            return {
                "id": row.id,
                "type": row.type,
                "value": row.value,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "result": json.loads(row.result_json) if row.result_json else None,
            }
        finally:
            session.close()

    def clear_history(self) -> int:
        """Удаляет все записи истории; возвращает количество удалённых."""
        from app.db.models import SearchHistory

        session = self._Session()
        try:
            deleted = session.query(SearchHistory).delete()
            session.commit()
            return deleted
        except Exception:
            session.rollback()
            return 0
        finally:
            session.close()

    # --- cache ---
    def get_cached(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        session = self._Session()
        try:
            row = (
                session.query(RequestCache)
                .filter_by(query_hash=_query_hash(query))
                .order_by(RequestCache.created_at.desc())
                .first()
            )
            if not row or not row.created_at:
                return None
            if datetime.utcnow() - row.created_at > timedelta(seconds=CACHE_TTL_SECONDS):
                return None
            return json.loads(row.result_json) if row.result_json else None
        finally:
            session.close()

    def set_cached(self, query: Dict[str, Any], result: Dict[str, Any]) -> None:
        session = self._Session()
        try:
            session.query(RequestCache).filter_by(query_hash=_query_hash(query)).delete()
            session.add(
                RequestCache(query_hash=_query_hash(query), result_json=json.dumps(result, ensure_ascii=False))
            )
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()
