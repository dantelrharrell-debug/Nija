from __future__ import annotations

import importlib
import os
from types import SimpleNamespace


def _module():
    return importlib.import_module("bot.runtime_execution_convergence_v32")


def test_v167_marker_and_reconciliation_guard_present():
    module = _module()
    assert module.REFRESH_DEMAND_MARKER == "20260819-runtime-refresh-demand-v167"
    assert getattr(module._request_runtime_reconciliation, "_nija_runtime_refresh_demand_v167", False)


def test_routine_refresh_is_owned_by_v137(monkeypatch):
    module = _module()
    manager = SimpleNamespace(_nija_capital_publication_deadline_v137_started=True)
    monkeypatch.setenv("NIJA_CAPITAL_PUBLICATION_DEADLINE_V137_INSTALLED", "1")

    fake_v137 = SimpleNamespace(
        _publication_refresh_due=lambda *a, **k: (False, {}),
        _execute_deadline_refresh=lambda *a, **k: True,
    )
    real_import = module.importlib.import_module

    def fake_import(name: str):
        if name == "bot.capital_publication_deadline_v137_patch":
            return fake_v137
        return real_import(name)

    monkeypatch.setattr(module.importlib, "import_module", fake_import)
    assert module._routine_refresh_owned_by_v137(manager) is True


def test_startup_refresh_not_ready_without_registration(monkeypatch):
    module = _module()

    class Event:
        def is_set(self):
            return False

    manager = SimpleNamespace(_broker_registration_complete=Event(), _startup_lock_released=False)
    assert module._startup_runtime_refresh_ready(manager) is False


def test_monitor_interval_has_no_immediate_zero_tick(monkeypatch):
    module = _module()
    monkeypatch.setenv("NIJA_RUNTIME_CONVERGENCE_INTERVAL_S", "30")
    assert module._monitor_interval_seconds() == 30.0
    monkeypatch.setenv("NIJA_RUNTIME_CONVERGENCE_INTERVAL_S", "1")
    assert module._monitor_interval_seconds() == 10.0


def test_install_sets_v167_prebot_attestation(monkeypatch):
    module = _module()
    monkeypatch.delenv("NIJA_RUNTIME_REFRESH_DEMAND_V167_PREBOT_READY", raising=False)
    assert module.install_import_hook() is True
    assert os.environ["NIJA_RUNTIME_REFRESH_DEMAND_V167_PREBOT_READY"] == "1"
