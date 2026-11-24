"""Тесты Aggregator: нормализация элементов, дедупликация, итоговый отчёт."""

from app.core.aggregator import Aggregator
from app.utils import normalizer


def _module_result_ok(module: str, items: list, error=None):
    return {"module": module, "status": "ok", "data": items, "error": error}


def test_aggregator_groups_by_type_and_dedupes():
    agg = Aggregator()
    query = {"type": "username", "value": "ray228a"}
    results = [
        _module_result_ok("username_module", [
            normalizer.norm(source="GitHub", url="https://github.com/ray228a", confidence="medium"),
            normalizer.norm(source="VK", url="https://vk.com/ray228a", confidence="medium"),
            # дубликат по url — должен быть удалён
            normalizer.norm(source="GitHub dup", url="https://github.com/ray228a", confidence="low"),
        ]),
    ]
    out = agg.aggregate(query, results)

    assert out["query"]["type"] == "username"
    assert out["results"]["username"] and len(out["results"]["username"]) == 2
    assert out["results"]["email"] == []
    urls = [r["url"] for r in out["results"]["username"] if r["url"]]
    assert urls.count("https://github.com/ray228a") == 1
    assert out["summary"]["total_found"] == 2
    assert out["summary"]["sources_used"] == 1
    assert out["errors"] == []


def test_aggregator_email_group():
    agg = Aggregator()
    out = agg.aggregate(
        {"type": "email", "value": "a@b.c"},
        [_module_result_ok("email_module", [normalizer.norm(source="leaked.directory", confidence="medium")])],
    )
    assert len(out["results"]["email"]) == 1


def test_aggregator_collects_errors():
    agg = Aggregator()
    query = {"type": "phone", "value": "+79161234567"}
    results = [
        {"module": "phone_module", "status": "error", "data": [], "error": "timeout"},
        _module_result_ok("social_module", []),
    ]
    out = agg.aggregate(query, results)
    assert out["errors"] == [{"module": "phone_module", "error": "timeout"}]
    assert out["summary"]["sources_used"] == 1


def test_aggregator_tolerates_unexpected_items():
    agg = Aggregator()
    query = {"type": "email", "value": "a@b.c"}
    results = [
        _module_result_ok("email_module", [
            {"source": "weird", "url": "https://weird.example", "confidence": "high"},  # без extra/type
            "garbage-string",  # не-dict
            {"unexpected": "key"},  # нет source
        ]),
    ]
    out = agg.aggregate(query, results)  # не должен падать
    assert isinstance(out["results"]["email"], list)


def test_aggregator_empty_results():
    agg = Aggregator()
    out = agg.aggregate({"type": "username", "value": "x"}, [])
    assert out["summary"]["total_found"] == 0
    assert out["id"]
    assert out["timestamp"]
