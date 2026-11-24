"""Тесты валидации запросов (app.api.schemas.SearchRequest)."""

import pytest
from pydantic import ValidationError

from app.api.schemas import SearchRequest


def test_rejects_bad_type():
    with pytest.raises(ValidationError):
        SearchRequest(type="bogus", value="x")


def test_rejects_empty_value():
    with pytest.raises(ValidationError):
        SearchRequest(type="username", value="   ")


def test_rejects_invalid_username():
    with pytest.raises(ValidationError):
        SearchRequest(type="username", value="bad name!")


def test_accepts_valid_username():
    req = SearchRequest(type="username", value="  some_user_123  ")
    assert req.type == "username"
    assert req.value == "some_user_123"


def test_rejects_invalid_phone():
    with pytest.raises(ValueError):
        SearchRequest(type="phone", value="not-a-phone")


def test_accepts_valid_phone():
    req = SearchRequest(type="phone", value="+79161234567")
    assert req.type == "phone"


def test_accepts_social_type():
    req = SearchRequest(type="social", value="Иван Петров, г. Москва")
    assert req.type == "social"
