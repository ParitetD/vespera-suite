"""Валидация входных данных (regex / phonenumbers)."""

import re
from typing import List, Optional

from phonenumbers import NumberParseException, format_number, is_valid_number, parse
from phonenumbers import PhoneNumberFormat
from pydantic import BaseModel, field_validator

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

ALLOWED_TYPES = {"username", "email", "phone", "social", "photo", "metadata"}


class SearchQuery(BaseModel):
    """Общий запрос: тип + значение (+ опциональный выбор модулей)."""

    type: str
    value: str
    modules: Optional[List[str]] = None

    @field_validator("type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        if v not in ALLOWED_TYPES:
            raise ValueError(f"unsupported type {v!r}; allowed: {sorted(ALLOWED_TYPES)}")
        return v

    @field_validator("value")
    @classmethod
    def _check_value(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("value is empty")
        return v


def validate_username(value: str) -> str:
    v = value.strip()
    if not USERNAME_RE.match(v):
        raise ValueError(f"invalid username: {v!r}")
    return v


def validate_email(value: str) -> str:
    v = value.strip().lower()
    if not EMAIL_RE.match(v):
        raise ValueError(f"invalid email: {v!r}")
    return v


def validate_phone(value: str, country_code: str = "RU") -> str:
    """Приводит к E.164 и проверяет валидность номера."""
    raw = value.strip()
    if not raw.startswith("+"):
        raw = "+" + raw.lstrip("+")
    try:
        number = parse(raw, country_code)
    except NumberParseException as exc:
        raise ValueError(f"invalid phone {value!r}: {exc}")
    if not is_valid_number(number):
        raise ValueError(f"invalid phone: {raw}")
    return format_number(number, PhoneNumberFormat.E164)
