from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import runtime_module_identity_convergence_patch as guard


def test_repeated_thread_recovery_reuses_same_module_without_duplicate_latch(monkeypatch):
    monkeypatch.delenv("NIJA_DUPLICATE_PATCH_MODULE_DETECTED", raising=False)
    globals_dict = {
        "__name__": guard._RISK_ALIAS,
        "__file__": "/app/bot/downstream_risk_governor_equity_repair_patch.py",
        "_MARKER": guard._REQUIRED_RISK_MARKER,
        "install_import_hook": lambda: None,
    }

    class Target:
        __globals__ = globals_dict

        def __call__(self):
            return None

    thread = SimpleNamespace(name="downstream-risk-v2-monitor", _target=Target())
    monkeypatch.setattr(guard.threading, "enumerate", lambda: [thread])
    monkeypatch.delitem(sys.modules, guard._RISK_ALIAS, raising=False)
    monkeypatch.delitem(sys.modules, guard._RISK_CANONICAL, raising=False)

    first = guard.recover_unregistered_patch_modules_from_threads()
    first_module = sys.modules[guard._RISK_CANONICAL]
    second = guard.recover_unregistered_patch_modules_from_threads()

    assert isinstance(first_module, ModuleType)
    assert sys.modules[guard._RISK_ALIAS] is first_module
    assert sys.modules[guard._RISK_CANONICAL] is first_module
    assert "duplicate=false" in first[guard._RISK_CANONICAL]
    assert "duplicate=false" in second[guard._RISK_CANONICAL]
    assert guard.os.environ.get("NIJA_DUPLICATE_PATCH_MODULE_DETECTED") != "1"
