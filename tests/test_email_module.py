"""Тесты EmailModule: нормализаторы + валидатор email + MX."""

import pytest

from app.modules.email_module import (
    _domain_of,
    _mx_records,
    _norm_hibp,
    _norm_leaked_directory,
)
from app.utils.validators import validate_email


def test_norm_hibp():
    out = _norm_hibp([{"Name": "Adobe", "Domain": "adobe.com", "PwnCount": 1300000000}])
    assert len(out) == 1
    assert out[0]["confidence"] == "high"
    assert "adobe" in out[0]["source"].lower()


def test_norm_leaked_directory_list():
    out = _norm_leaked_directory(["Adobe", "LinkedIn"])
    assert len(out) == 2
    assert out[0]["source"] == "leaked.directory"
    assert "Adobe" in out[0]["title"]


def test_norm_leaked_directory_dict():
    out = _norm_leaked_directory({"result": ["Example"]})
    assert len(out) == 1
    assert out[0]["source"] == "leaked.directory"


def test_mx_records_empty_on_bad_domain():
    assert _mx_records("nonexistent-domain-xyz-12345.invalid") == []


def test_domain_of():
    assert _domain_of("User@Example.COM ") == "example.com"


def test_validate_email():
    assert validate_email(" User@Example.COM ") == "user@example.com"
    with pytest.raises(ValueError):
        validate_email("not-an-email")
