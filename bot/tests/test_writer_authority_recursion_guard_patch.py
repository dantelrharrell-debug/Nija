from __future__ import annotations

import sys
import time
from types import ModuleType

from bot import writer_authority_recursion_guard_patch as patch


def test_status_reentry_guard_returns_cached_result(monkeypatch):
    module = ModuleType("bot.execution_authority_context")
    module._FENCE_LAST_OK = True
    module._FENCE_LAST_ERR = ""
    module._FENCE_LAST_CHECK_TS = 0.0

    def recursive_status(force_refresh=False):
        return module.get_distributed_writer_authority_status(force_refresh=force_refresh)

    module.get_distributed_writer_authority_status = recursive_status
    assert patch._patch_execution_authority_context(module) is True

    result = module.get_distributed_writer_authority_status()

    assert isinstance(result, dict)
    assert "ok" in result
    assert "cache" in result


def test_status_reentry_guard_accepts_fresh_writer_proof(monkeypatch):
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("NIJA_REDIS_URL", "redis://example")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "tok-123")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "42")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", str(time.time()))

    module = ModuleType("bot.execution_authority_context")
    module._FENCE_LAST_OK = False
    module._FENCE_LAST_ERR = ""
    module._FENCE_LAST_CHECK_TS = 0.0

    def recursive_status(force_refresh=False):
        return module.get_distributed_writer_authority_status(force_refresh=force_refresh)

    module.get_distributed_writer_authority_status = recursive_status
    assert patch._patch_execution_authority_context(module) is True

    result = module.get_distributed_writer_authority_status()

    assert result["ok"] is True
    assert result["redis_reachable"] is True
    assert result["authority_verified"] is True
    assert result["token_present"] is True
    assert result["lease_generation"] == "42"
    assert result["cache"]["reentry_proof_ok"] is True


def test_status_reentry_guard_fails_closed_without_fresh_writer_proof(monkeypatch):
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("NIJA_REDIS_URL", "redis://example")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "tok-123")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "42")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", str(time.time() - 999.0))

    module = ModuleType("bot.execution_authority_context")
    module._FENCE_LAST_OK = False
    module._FENCE_LAST_ERR = ""
    module._FENCE_LAST_CHECK_TS = 0.0

    def recursive_status(force_refresh=False):
        return module.get_distributed_writer_authority_status(force_refresh=force_refresh)

    module.get_distributed_writer_authority_status = recursive_status
    assert patch._patch_execution_authority_context(module) is True

    result = module.get_distributed_writer_authority_status()

    assert result["ok"] is False
    assert result["redis_reachable"] is False
    assert result["authority_verified"] is False
    assert result["cache"]["reentry_proof_ok"] is False


def test_trading_state_writer_gate_uses_direct_distributed_assert(monkeypatch):
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "tok-123")
    monkeypatch.setenv("NIJA_REDIS_LOCK_RETRIES", "1")

    tsm = ModuleType("bot.trading_state_machine")
    tsm._resolve_writer_fencing_token = lambda manager=None: "tok-123"

    dn = ModuleType("bot.distributed_nonce_manager")
    dn.get_distributed_nonce_manager = lambda: object()
    sys.modules["bot.distributed_nonce_manager"] = dn

    eac = ModuleType("bot.execution_authority_context")
    calls = {"distributed": 0, "startup": 0}

    def assert_distributed_writer_authority():
        calls["distributed"] += 1

    def assert_startup_write_authority():
        calls["startup"] += 1
        raise AssertionError("startup authority should not be called by patched writer gate")

    eac.assert_distributed_writer_authority = assert_distributed_writer_authority
    eac.assert_startup_write_authority = assert_startup_write_authority
    sys.modules["bot.execution_authority_context"] = eac

    assert patch._patch_trading_state_machine(tsm) is True
    ok, err = tsm._distributed_writer_authority_gate()

    assert ok is True
    assert err == ""
    assert calls["distributed"] == 1
    assert calls["startup"] == 0


def test_trading_state_writer_gate_fails_closed_on_distributed_error(monkeypatch):
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "tok-123")
    monkeypatch.setenv("NIJA_REDIS_LOCK_RETRIES", "1")
    monkeypatch.delenv("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK", raising=False)

    tsm = ModuleType("bot.trading_state_machine")
    tsm._resolve_writer_fencing_token = lambda manager=None: "tok-123"

    dn = ModuleType("bot.distributed_nonce_manager")
    dn.get_distributed_nonce_manager = lambda: object()
    sys.modules["bot.distributed_nonce_manager"] = dn

    eac = ModuleType("bot.execution_authority_context")

    def assert_distributed_writer_authority():
        raise RuntimeError("redis unavailable")

    eac.assert_distributed_writer_authority = assert_distributed_writer_authority
    sys.modules["bot.execution_authority_context"] = eac

    assert patch._patch_trading_state_machine(tsm) is True
    ok, err = tsm._distributed_writer_authority_gate()

    assert ok is False
    assert "LIVE TRADING BLOCKED" in err
    assert "redis unavailable" in err
