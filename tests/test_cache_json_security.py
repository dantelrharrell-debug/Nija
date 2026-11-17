"""Exercise the cache boundary with an in-memory Redis substitute only."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import Mock

import pytest


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> tuple[types.ModuleType, Mock]:
    """Load the real cache module without importing the trading bootstrap."""
    redis = types.ModuleType("redis")
    redis.Redis = type("Redis", (), {})
    connection = types.ModuleType("redis.connection")
    connection.ConnectionPool = type("ConnectionPool", (), {})
    redis_env = types.ModuleType("bot.redis_env")
    redis_env.get_redis_url = Mock(side_effect=AssertionError("No Redis connection allowed"))
    redis_env.get_redis_url_source = Mock(return_value="offline-test")
    redis_runtime = types.ModuleType("bot.redis_runtime")
    redis_runtime.connect_redis_with_fallback = Mock(side_effect=AssertionError("No connection allowed"))
    redis_runtime.get_redis_tls_kwargs = Mock(side_effect=AssertionError("No connection allowed"))
    for name, module in (("redis", redis), ("redis.connection", connection),
                         ("bot.redis_env", redis_env), ("bot.redis_runtime", redis_runtime)):
        monkeypatch.setitem(sys.modules, name, module)
    source = Path(__file__).resolve().parents[1] / "cache" / "redis_client.py"
    spec = importlib.util.spec_from_file_location("isolated_json_cache", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = Mock()
    client.values = {}
    client.set.side_effect = lambda key, value: client.values.__setitem__(key, value)
    client.setex.side_effect = lambda key, ttl, value: client.values.__setitem__(key, value)
    client.get.side_effect = lambda key: client.values.get(key)
    monkeypatch.setattr(module, "get_redis_client", lambda: client)
    return module, client


@pytest.mark.parametrize("value", [
    {"prices": [1.25, 2], "ready": False, "label": "market"},
    ["read", "view"], "quoted string", "123", "true", "null", 42, 1.25, True, False, None,
])
def test_json_values_round_trip_without_executable_deserialization(
    cache: tuple[types.ModuleType, Mock], value: object
) -> None:
    module, client = cache
    assert module.cache_set("entry", value, ttl=60, namespace="market:")
    actual = module.cache_get("entry", namespace="market:")
    assert actual == value
    assert type(actual) is type(value)
    client.setex.assert_called_once()
    assert isinstance(client.values["market:entry"], str)


@pytest.mark.parametrize("value", [object(), b"binary", {"bad": object()}, float("nan"), float("inf")])
def test_unsupported_writes_fail_without_modifying_cache(
    cache: tuple[types.ModuleType, Mock], value: object
) -> None:
    module, client = cache
    assert not module.cache_set("entry", value)
    client.set.assert_not_called()
    client.setex.assert_not_called()
    assert client.values == {}


@pytest.mark.parametrize("stored, expected", [
    (b'{"authenticated": false}', {"authenticated": False}),
    (b"legacy label", "legacy label"), ("False", "False"), (b"123", 123),
])
def test_existing_json_and_plain_scalar_entries_remain_readable(
    cache: tuple[types.ModuleType, Mock], stored: object, expected: object
) -> None:
    module, client = cache
    client.values["entry"] = stored
    assert module.cache_get("entry") == expected


@pytest.mark.parametrize("prefix", [b"", b"\x80\x02"])
def test_object_reconstruction_payload_never_invokes_callable(
    cache: tuple[types.ModuleType, Mock], monkeypatch: pytest.MonkeyPatch, prefix: bytes
) -> None:
    module, client = cache
    probe = types.ModuleType("cache_payload_probe")
    probe.record = Mock(return_value="executed")
    monkeypatch.setitem(sys.modules, "cache_payload_probe", probe)
    # A GLOBAL + REDUCE object stream; if decoded as a Python object, it calls
    # the harmless probe. It contains no shell command and opens no connection.
    payload = prefix + b"ccache_payload_probe\nrecord\n(tR."
    client.values["entry"] = payload
    result = module.cache_get("entry", default="missing")
    probe.record.assert_not_called()
    assert result != "executed"
    if prefix:
        assert result == "missing"


def test_cache_miss_and_invalid_binary_use_default(cache: tuple[types.ModuleType, Mock]) -> None:
    module, client = cache
    assert module.cache_get("missing", default="fallback") == "fallback"
    client.values["entry"] = b"\xff\xfe"
    assert module.cache_get("entry", default="fallback") == "fallback"


def test_in_repo_market_session_and_permissions_wrappers_keep_json_contract(
    cache: tuple[types.ModuleType, Mock]
) -> None:
    module, client = cache
    assert module.cache_market_data("BTCUSD", "1m", {"price": 1.0})
    assert module.get_cached_market_data("BTCUSD", "1m") == {"price": 1.0}
    assert module.cache_user_session("offline-user", {"authenticated": False})
    assert module.get_cached_user_session("offline-user") == {"authenticated": False}
    assert module.cache_user_permissions("offline-user", {"can_trade": False})
    assert module.get_cached_user_permissions("offline-user") == {"can_trade": False}


@pytest.mark.parametrize("reader, key, args", [
    ("get_cached_market_data", "market:BTCUSD:1m", ("BTCUSD", "1m")),
    ("get_cached_user_session", "session:offline-user", ("offline-user",)),
    ("get_cached_user_permissions", "perm:offline-user", ("offline-user",)),
])
@pytest.mark.parametrize("stored", [
    b"legacy plain scalar", b"ccache_payload_probe\nrecord\n(tR.",
    b"\x80\x02ccache_payload_probe\nrecord\n(tR.", b'["read", "view"]',
    b'"authenticated"', b"123", b"true", b"null", b"\xff\xfe", None,
])
def test_dictionary_consumers_treat_other_cached_shapes_as_misses_without_mutation(
    cache: tuple[types.ModuleType, Mock], monkeypatch: pytest.MonkeyPatch,
    reader: str, key: str, args: tuple[str, ...], stored: object,
) -> None:
    """Inert legacy object text must not reach callers expecting dictionaries."""
    module, client = cache
    probe = types.ModuleType("cache_payload_probe")
    probe.record = Mock(return_value={"unexpected": "object reconstruction"})
    monkeypatch.setitem(sys.modules, "cache_payload_probe", probe)
    client.values[key] = stored
    original = dict(client.values)

    assert getattr(module, reader)(*args) is None

    probe.record.assert_not_called()
    assert client.values == original
    client.set.assert_not_called()
    client.setex.assert_not_called()
    client.delete.assert_not_called()
    client.flushdb.assert_not_called()
    client.flushall.assert_not_called()


@pytest.mark.parametrize("reader, key, args", [
    ("get_cached_market_data", "market:BTCUSD:1m", ("BTCUSD", "1m")),
    ("get_cached_user_session", "session:offline-user", ("offline-user",)),
    ("get_cached_user_permissions", "perm:offline-user", ("offline-user",)),
])
def test_dictionary_consumers_preserve_empty_dictionaries(
    cache: tuple[types.ModuleType, Mock], reader: str, key: str, args: tuple[str, ...],
) -> None:
    """An empty JSON dictionary is a valid hit rather than a falsey miss."""
    module, client = cache
    client.values[key] = b"{}"
    assert getattr(module, reader)(*args) == {}
