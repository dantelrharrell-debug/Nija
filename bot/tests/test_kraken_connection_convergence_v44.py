from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "kraken_connection_convergence_v44_patch.py"


def _load_module(name: str = "test_kraken_connection_convergence_v44_patch"):
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _fake_v24(*, started: bool, ready: bool = True):
    calls = []
    module = types.ModuleType("fake_v24")
    module._KRAKEN_RECOVERY_STARTED = started
    module._writer_lineage = lambda: (True, "lineage_ready generation=44")
    module._kraken_credentials_configured = lambda: True

    def _start(manager):
        calls.append(manager)
        module._KRAKEN_RECOVERY_STARTED = True
        return True

    module._start_kraken_authenticated_recovery = _start
    if ready:
        os.environ["NIJA_KRAKEN_AUTHENTICATED_RECOVERY_READY"] = "1"
    else:
        os.environ["NIJA_KRAKEN_AUTHENTICATED_RECOVERY_READY"] = "0"
    return module, calls


class _Broker:
    def __init__(self, connected: bool):
        self.connected = connected


class TestKrakenConnectionConvergenceV44:
    def teardown_method(self):
        os.environ.pop("NIJA_KRAKEN_AUTHENTICATED_RECOVERY_READY", None)

    def test_stale_success_latch_is_rearmed_only_when_disconnected(self):
        module = _load_module("v44_test_rearm")
        v24, _calls = _fake_v24(started=True, ready=True)
        broker = _Broker(connected=False)

        assert module._rearm_if_stale_success(v24, broker) is True
        assert v24._KRAKEN_RECOVERY_STARTED is False
        assert os.environ["NIJA_KRAKEN_AUTHENTICATED_RECOVERY_READY"] == "0"

    def test_connected_broker_never_rearms_recovery(self):
        module = _load_module("v44_test_connected")
        v24, _calls = _fake_v24(started=True, ready=True)
        broker = _Broker(connected=True)

        assert module._rearm_if_stale_success(v24, broker) is False
        assert v24._KRAKEN_RECOVERY_STARTED is True
        assert os.environ["NIJA_KRAKEN_AUTHENTICATED_RECOVERY_READY"] == "1"

    def test_inflight_recovery_is_not_interrupted(self):
        module = _load_module("v44_test_inflight")
        v24, _calls = _fake_v24(started=True, ready=False)
        broker = _Broker(connected=False)

        assert module._rearm_if_stale_success(v24, broker) is False
        assert v24._KRAKEN_RECOVERY_STARTED is True

    def test_reconcile_starts_existing_authenticated_recovery(self, monkeypatch):
        module = _load_module("v44_test_start")
        v24, calls = _fake_v24(started=False, ready=False)
        manager = object()
        broker = _Broker(connected=False)

        monkeypatch.setattr(module, "_v24", lambda: v24)
        monkeypatch.setattr(module, "_manager", lambda: manager)
        monkeypatch.setattr(module, "_canonical_kraken", lambda _manager: broker)
        monkeypatch.setattr(module, "_permanent_failure_latched", lambda: False)

        result = module.reconcile_once()

        assert result["ok"] is True
        assert result["action"] == "recovery_started"
        assert result["connected"] is False
        assert calls == [manager]
        # v44 does not fabricate connection state; the existing recovery owns it.
        assert broker.connected is False

    def test_reconcile_rearms_stale_success_then_restarts(self, monkeypatch):
        module = _load_module("v44_test_restart")
        v24, calls = _fake_v24(started=True, ready=True)
        manager = object()
        broker = _Broker(connected=False)

        monkeypatch.setattr(module, "_v24", lambda: v24)
        monkeypatch.setattr(module, "_manager", lambda: manager)
        monkeypatch.setattr(module, "_canonical_kraken", lambda _manager: broker)
        monkeypatch.setattr(module, "_permanent_failure_latched", lambda: False)

        result = module.reconcile_once()

        assert result["ok"] is True
        assert result["action"] == "recovery_started"
        assert result["reason"] == "stale_success_rearmed"
        assert calls == [manager]

    def test_permanent_auth_failure_remains_fail_closed(self, monkeypatch):
        module = _load_module("v44_test_perm")
        v24, calls = _fake_v24(started=False, ready=False)

        monkeypatch.setattr(module, "_v24", lambda: v24)
        monkeypatch.setattr(module, "_permanent_failure_latched", lambda: True)

        result = module.reconcile_once()

        assert result["ok"] is False
        assert result["action"] == "none"
        assert result["reason"] == "permanent_auth_or_config_failure_latched"
        assert calls == []

    def test_missing_writer_lineage_never_starts_recovery(self, monkeypatch):
        module = _load_module("v44_test_lineage")
        v24, calls = _fake_v24(started=False, ready=False)
        v24._writer_lineage = lambda: (False, "lease_not_acquired")

        monkeypatch.setattr(module, "_v24", lambda: v24)
        monkeypatch.setattr(module, "_permanent_failure_latched", lambda: False)

        result = module.reconcile_once()

        assert result["ok"] is False
        assert result["reason"] == "lease_not_acquired"
        assert calls == []

    def test_already_connected_does_not_start_duplicate_recovery(self, monkeypatch):
        module = _load_module("v44_test_no_duplicate")
        v24, calls = _fake_v24(started=False, ready=False)
        manager = object()
        broker = _Broker(connected=True)

        monkeypatch.setattr(module, "_v24", lambda: v24)
        monkeypatch.setattr(module, "_manager", lambda: manager)
        monkeypatch.setattr(module, "_canonical_kraken", lambda _manager: broker)
        monkeypatch.setattr(module, "_permanent_failure_latched", lambda: False)

        result = module.reconcile_once()

        assert result["ok"] is True
        assert result["reason"] == "already_connected"
        assert result["connected"] is True
        assert calls == []
