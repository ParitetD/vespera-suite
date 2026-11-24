"""Тесты UsernameModule: валидация + _check_site против локального HTTP-сервера + fallback."""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from app.modules.username_module import (
    UsernameModule,
    _check_site,
    _manual_fallback,
    load_wmn_sites,
)
from app.utils.validators import validate_username


def test_validate_username():
    assert validate_username(" Some_User-1.2 ") == "Some_User-1.2"
    with pytest.raises(ValueError):
        validate_username("bad name!")


def test_wmn_sites_loaded():
    assert len(load_wmn_sites()) > 100


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/users/found-user"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html><body>OK</body></html>")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def test_check_site_found_and_not_found():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    site = {
        "name": "LocalSite",
        "uri_check": f"http://127.0.0.1:{port}/users/{{account}}",
        "e_code": 200,
        "e_string": "",
        "m_code": 404,
        "m_string": "",
    }

    async def run():
        async with httpx.AsyncClient() as client:
            found = await _check_site(client, site, "found-user")
            missing = await _check_site(client, site, "nope")
        return found, missing

    try:
        found, missing = asyncio.run(run())
    finally:
        server.shutdown()

    assert found is not None
    assert found["url"].endswith("/users/found-user")
    assert found["confidence"] == "medium"
    assert missing is None


def test_manual_fallback_structure():
    fb = _manual_fallback({"name": "TestSite", "uri_check": "https://example.com/{account}"}, "abc")
    assert fb["confidence"] == "info"
    assert "abc" in (fb["url"] or "")


def test_username_module_supports_username():
    assert "username" in UsernameModule.supported_inputs
