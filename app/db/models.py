"""SQLAlchemy модели: история запросов + cache."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class SearchHistory(Base):
    """История поисковых запросов и их отчётов."""

    __tablename__ = "search_history"

    id = Column(String(64), primary_key=True)
    type = Column(String(32), nullable=False)
    value = Column(String(512), nullable=False)
    result_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<SearchHistory {self.type} {self.value[:40]!r}>"


class RequestCache(Base):
    """Cache уже выполненных запросов (dedupe повторов)."""

    __tablename__ = "request_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query_hash = Column(String(64), nullable=False, unique=True)
    result_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
