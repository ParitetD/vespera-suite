"""Pydantic-модели запросов/ответов API."""

from typing import List, Optional

from pydantic import BaseModel, model_validator

from app.utils.validators import ALLOWED_TYPES, SearchQuery, validate_email, validate_phone, validate_username


class SearchRequest(BaseModel):
    """Запрос: type + value + опциональный выбор модулей."""

    type: str
    value: str
    modules: Optional[List[str]] = None

    @model_validator(mode="after")
    def _check(self) -> "SearchRequest":
        if self.type not in ALLOWED_TYPES:
            raise ValueError(f"unsupported type {self.type!r}; allowed: {sorted(ALLOWED_TYPES)}")
        v = self.value.strip()
        if not v:
            raise ValueError("value is empty")
        if self.type == "username":
            v = validate_username(v)
        elif self.type == "email":
            v = validate_email(v)
        elif self.type == "phone":
            v = validate_phone(v)
        self.value = v
        return self


__all__ = ["SearchRequest", "SearchQuery"]
