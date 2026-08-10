from __future__ import annotations

import sys
import threading
import types
from unittest.mock import MagicMock, patch

from bot.entrypoint_writer_authority import EntrypointWriterAuthority


def _runtime() -> EntrypointWriterAuthority:
    runtime = EntrypointWriterAuthority()
    runtime._client = MagicMock()
    runtime._client.eval.return_value = 1
    runtime._lock_key = "lock"
    runtime._meta_key = "meta"
    runtime._fencing_key = "fence"
    runtime._lock_value = "11:owner"
    runtime._token = "11"
    runtime._generation = 7
    runtime._instance_id = "test"
    runtime._identity = {"instance_id": "test"}
    runtime._owner = "owner"
    runtime._ttl_s = 60
    runtime._acquired_at = 1.0
    runtime._core_thread = MagicMock()
    runtime._core_thread.is_alive.return_value = True
    return runtime


def test_slow_readiness_reconciliation_never_blocks_redis_renewal() -> None:
    runtime = _runtime()
    started = threading.Event()
    release = threading.Event()
    calls: list[dict[str, object]] = []
    readiness = types.ModuleType("three_venue_execution_readiness")

    def reconcile(**kwargs: object) -> None:
        calls.append(kwargs)
        started.set()
        release.wait(2.0)

    readiness.reconcile_execution_readiness = reconcile
    with patch.dict(sys.modules, {"three_venue_execution_readiness": readiness}):
        ok, reason = runtime._heartbeat_tick()
        assert ok is True
        assert reason == ""
        assert started.wait(1.0)

        # A second renewal succeeds while the first readiness pass is blocked,
        # and it does not create another broker-I/O worker.
        ok, reason = runtime._heartbeat_tick()
        assert ok is True
        assert reason == ""
        assert calls == [{"trigger": "heartbeat_renewed", "force": True}]
        assert runtime._client.eval.call_count == 2
        release.set()


def test_non_heartbeat_reconciliation_remains_synchronous() -> None:
    runtime = _runtime()
    calls: list[dict[str, object]] = []
    readiness = types.ModuleType("three_venue_execution_readiness")
    readiness.reconcile_execution_readiness = lambda **kwargs: calls.append(kwargs)

    with patch.dict(sys.modules, {"three_venue_execution_readiness": readiness}):
        runtime._notify_runtime_reconciliation("core_thread_registered")

    assert calls == [{"trigger": "core_thread_registered", "force": True}]
