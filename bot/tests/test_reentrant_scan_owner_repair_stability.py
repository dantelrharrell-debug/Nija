from __future__ import annotations

from types import ModuleType, SimpleNamespace

import reentrant_scan_owner_repair as repair
import scan_owner_okx_auth_convergence_patch as convergence


def test_repair_prevents_convergence_rewrap(monkeypatch):
    module = ModuleType("bot.nija_core_loop")

    class NijaCoreLoop:
        def run_scan_phase(self, *args, **kwargs):
            return SimpleNamespace(
                symbols_scored=5,
                entries_taken=0,
                entries_blocked=0,
                exits_taken=0,
                next_interval=15,
            )

    module.NijaCoreLoop = NijaCoreLoop
    assert convergence._patch_core(module) is True
    assert getattr(NijaCoreLoop.run_scan_phase, repair._PATCH_ATTR, False)

    assert repair._repair_module(module) is True
    canonical = NijaCoreLoop.run_scan_phase
    assert getattr(canonical, repair._REPAIR_ATTR, False)

    repair._install_convergence_guard()
    assert convergence._patch_core(module) is True
    assert NijaCoreLoop.run_scan_phase is canonical
