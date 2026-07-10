from __future__ import annotations

from render_runtime_bootstrap import apply_render_private_redis_fallback


def test_noop_outside_render() -> None:
    env: dict[str, str] = {}
    assert apply_render_private_redis_fallback(env) == ""
    assert "NIJA_REDIS_URL" not in env


def test_preserves_existing_valid_redis_url() -> None:
    env = {
        "RENDER_SERVICE_ID": "srv-example",
        "NIJA_REDIS_URL": "redis://existing.internal:6379",
    }
    assert apply_render_private_redis_fallback(env) == ""
    assert env["NIJA_REDIS_URL"] == "redis://existing.internal:6379"
    assert "NIJA_RENDER_REDIS_FALLBACK_APPLIED" not in env


def test_applies_known_private_render_fallback() -> None:
    env = {"RENDER_SERVICE_ID": "srv-example"}
    resolved = apply_render_private_redis_fallback(env)
    assert resolved == "redis://red-d98dsl5aeets73fpb0hg:6379"
    assert env["NIJA_REDIS_URL"] == resolved
    assert env["REDIS_URL"] == resolved
    assert env["NIJA_RENDER_REDIS_FALLBACK_APPLIED"] == "1"


def test_accepts_valid_operator_override() -> None:
    env = {
        "RENDER_SERVICE_ID": "srv-example",
        "NIJA_RENDER_REDIS_FALLBACK_URL": "redis://red-override123:6379",
    }
    assert apply_render_private_redis_fallback(env) == "redis://red-override123:6379"


def test_rejects_public_or_malformed_override() -> None:
    env = {
        "RENDER_SERVICE_ID": "srv-example",
        "NIJA_RENDER_REDIS_FALLBACK_URL": "rediss://example.com:6380",
    }
    assert apply_render_private_redis_fallback(env) == ""
    assert "NIJA_REDIS_URL" not in env
