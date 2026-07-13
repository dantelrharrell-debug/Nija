from __future__ import annotations

import sys
from types import ModuleType

import reentrant_scan_owner_repair as repair


def _module_with_method(method):
    module = ModuleType("bot.nija_core_loop")

    class NijaCoreLoop:
        pass

    NijaCoreLoop.run_scan_phase = method
    module.NijaCoreLoop = NijaCoreLoop
    return module


def test_wrapper_chain_helper_detects_nested_repair_marker():
    def canonical(self, *args, **kwargs):
        return "ok"

    setattr(canonical, repair._REPAIR_ATTR, True)

    def venue_wrapper(self, *args, **kwargs):
        return canonical(self, *args, **kwargs)

    venue_wrapper.__wrapped__ = canonical
    assert repair._wrapper_chain_has_attr(venue_wrapper, repair._REPAIR_ATTR)


def test_repair_marker_is_promoted_to_legitimate_outer_wrapper():
    def canonical(self, *args, **kwargs):
        return "ok"

    setattr(canonical, repair._REPAIR_ATTR, True)

    def venue_wrapper(self, *args, **kwargs):
        return canonical(self, *args, **kwargs)

    venue_wrapper.__wrapped__ = canonical
    module = _module_with_method(venue_wrapper)

    assert repair._repair_module(module) is True
    assert getattr(module.NijaCoreLoop.run_scan_phase, repair._REPAIR_ATTR, False)
    assert module.NijaCoreLoop.run_scan_phase is venue_wrapper


def test_convergence_guard_does_not_rewrap_repaired_chain(monkeypatch):
    calls = {"count": 0}
    convergence = ModuleType("scan_owner_okx_auth_convergence_patch")

    def original_patch_core(module):
        calls["count"] += 1
        return True

    convergence._patch_core = original_patch_core
    monkeypatch.setitem(sys.modules, "scan_owner_okx_auth_convergence_patch", convergence)

    def canonical(self, *args, **kwargs):
        return "ok"

    setattr(canonical, repair._REPAIR_ATTR, True)

    def venue_wrapper(self, *args, **kwargs):
        return canonical(self, *args, **kwargs)

    venue_wrapper.__wrapped__ = canonical
    module = _module_with_method(venue_wrapper)

    assert repair._install_convergence_guard() is True
    assert convergence._patch_core(module) is True
    assert calls["count"] == 0
    assert module.NijaCoreLoop.run_scan_phase is venue_wrapper
    assert getattr(venue_wrapper, repair._REPAIR_ATTR, False)
