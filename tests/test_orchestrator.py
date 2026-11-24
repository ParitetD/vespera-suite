"""Тесты Orchestrator: агрегация + изоляция отказов модулей."""

import asyncio

from app.core.orchestrator import Orchestrator
from app.modules.base import BaseModule
from app.utils import normalizer


class DummyModule(BaseModule):
    name = "dummy_ok"
    supported_inputs = ["username"]

    async def search(self, query):
        return [
            normalizer.norm(
                source="dummy",
                url=f"https://dummy.example/{query['value']}",
                title="Dummy result",
                confidence="high",
                verified=True,
            )
        ]


class BrokenModule(BaseModule):
    name = "dummy_broken"
    supported_inputs = ["username"]

    async def search(self, query):
        raise RuntimeError("boom")


class EmailOnlyModule(BaseModule):
    name = "email_only"
    supported_inputs = ["email"]

    async def search(self, query):
        return []


def test_orchestrator_aggregates_and_isolates_errors():
    orch = Orchestrator(modules=[DummyModule(), BrokenModule()])
    result = asyncio.run(orch.run({"type": "username", "value": "testuser"}))

    assert result["query"]["value"] == "testuser"
    assert result["results"]["username"][0]["source"] == "dummy"
    assert result["results"]["username"][0]["url"] == "https://dummy.example/testuser"
    # падение одного модуля не ломает остальные
    assert result["summary"]["total_found"] == 1
    assert result["summary"]["sources_used"] == 1
    broken = [e for e in result["errors"] if e["module"] == "dummy_broken"]
    assert broken and "boom" in broken[0]["error"]


def test_module_skips_unsupported_type():
    orch = Orchestrator(modules=[DummyModule()])
    result = asyncio.run(orch.run({"type": "email", "value": "x@y.z"}))
    assert result["results"]["email"] == []
    assert result["summary"]["sources_used"] == 0


def test_module_whitelist_filter():
    orch = Orchestrator(modules=[DummyModule(), EmailOnlyModule()])
    result = asyncio.run(
        orch.run({"type": "username", "value": "testuser", "modules": ["email_only"]})
    )
    assert result["summary"]["sources_used"] == 0
