from __future__ import annotations

import importlib.util
import os
import sys
import threading
import time
import types
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "kraken_connection_convergence_v44_patch.py"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _AliveThread:
    def is_alive(self):
        return True


class _Client:
    def __init__(self, lock_value: str, token: str, generation: int, heartbeat_at: float):
        self.values = {
            "lock": lock_value,
            "fence": token,
            "generation": str(generation),
            "meta": (
                '{"token":"%s","generation":%d,"heartbeat_at":%.6f}'
                % (token, generation, heartbeat_at)
            ),
        }
        self.pttl_ms = 55000

    def get(self, key):
        return self.values.get(key)

    def pttl(self, key):
        assert key == "lock"
        return self.pttl_ms


class _Runtime:
    def __init__(self):
        self.acquired = True
        self.lost = False
        self._local_fallback = False
        self._stop = threading.Event()
        self._heartbeat_thread = _AliveThread()
        self._lock_key = "lock"
        self._meta_key = "meta"
        self._fencing_key = "fence"
        self._lock_value = "2080:owner"
        self._token = "2080"
        self._generation = 3383
        self._ttl_s = 60
        self._client = _Client(
            self._lock_value,
            self._token,
            self._generation,
            time.time(),
        )
        self.reconciled = []

    def _nija_lease_renewal_health(self):
        return False, "renewal_success_stale", 100.5, 15.0

    def _notify_runtime_reconciliation(self, trigger):
        self.reconciled.append(trigger)


class _Broker:
    def __init__(self, connected: bool):
        self.connected = connected


class _BrokerType:
    value = "kraken"


class TestPostV59RuntimeConvergenceV60:
    def setup_method(self):
        os.environ["NIJA_LEASE_GENERATION_KEY"] = "generation"
        os.environ["NIJA_WRITER_HEARTBEAT_INTERVAL_S"] = "5"

    def teardown_method(self):
        os.environ.pop("NIJA_LEASE_GENERATION_KEY", None)
        os.environ.pop("NIJA_WRITER_HEARTBEAT_INTERVAL_S", None)
        os.environ.pop("NIJA_WRITER_LEASE_RENEWAL_ACTIVE", None)
        os.environ.pop("NIJA_WRITER_LEASE_RENEWED_TS", None)

    def test_exact_redis_proof_reanchors_only_local_renewal_timestamp(self):
        module = _load("v60_writer_reanchor")
        runtime = _Runtime()
        original_values = dict(runtime._client.values)
        original_pttl = runtime._client.pttl_ms

        result = module.reconcile_writer_renewal_once(runtime)

        assert result["ok"] is True
        assert result["action"] == "reanchored"
        assert result["reason"] == "exact_redis_writer_renewal_proof"
        assert runtime._nija_last_lease_renewal_monotonic > 0
        assert os.environ["NIJA_WRITER_LEASE_RENEWAL_ACTIVE"] == "1"
        assert runtime.reconciled == ["post_v59_exact_writer_renewal_reanchor_v60"]
        assert runtime._client.values == original_values
        assert runtime._client.pttl_ms == original_pttl

    def test_writer_reanchor_fails_closed_on_generation_mismatch(self):
        module = _load("v60_writer_mismatch")
        runtime = _Runtime()
        runtime._client.values["generation"] = "3384"

        result = module.reconcile_writer_renewal_once(runtime)

        assert result["ok"] is False
        assert result["action"] == "none"
        assert "generation_mismatch" in result["reason"]
        assert not hasattr(runtime, "_nija_last_lease_renewal_monotonic")

    def test_invalid_nonce_is_retryable_but_bad_key_remains_permanent(self):
        module = _load("v60_nonce_classification")
        supervisor = types.ModuleType("fake_kraken_supervisor_v60")

        def original(error_str: str) -> bool:
            lowered = error_str.lower()
            return "invalid nonce" in lowered or "invalid key" in lowered

        supervisor._is_permanent_failure = original
        assert module._patch_supervisor_module(supervisor) is True
        assert supervisor._is_permanent_failure("EAPI:Invalid nonce") is False
        assert supervisor._is_permanent_failure("EAPI:Invalid key") is True

    def test_connected_kraken_repairs_stale_failed_platform_state(self):
        module = _load("v60_manager_wait")
        manager_module = types.ModuleType("fake_manager_v60")

        class Manager:
            def __init__(self):
                self._platform_brokers = {_BrokerType: _Broker(True)}
                self._platform_state = {"kraken": "failed"}
                self._platform_failed_types = {_BrokerType}
                self._platform_connected = {"kraken": False}
                self.marked = []

            def _mark_platform_connected(self, broker_type):
                self.marked.append(broker_type)
                self._platform_state["kraken"] = "connected"
                self._platform_failed_types.discard(broker_type)
                self._platform_connected["kraken"] = True

            def wait_for_platform_ready(self, broker_type, timeout=None):
                return False

        manager_module.MultiAccountBrokerManager = Manager
        assert module._patch_manager_module(manager_module) is True
        manager = Manager()

        assert manager.wait_for_platform_ready(_BrokerType) is True
        assert manager._platform_connected["kraken"] is True
        assert _BrokerType not in manager._platform_failed_types
        assert manager.marked == [_BrokerType]
