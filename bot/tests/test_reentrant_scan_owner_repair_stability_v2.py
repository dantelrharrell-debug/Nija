from __future__ import annotations

from types import ModuleType, SimpleNamespace

import reentrant_scan_owner_repair as repair
import scan_owner_okx_auth_convergence_patch as convergence


def test_repaired_scan_is_not_rewrapped():
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
    assert repair._repair_module(module) is True
    canonical = NijaCoreLoop.run_scan_phase

    assert repair._install_convergence_guard() is True
    assert convergence._patch_core(module) is True
    assert NijaCoreLoop.run_scan_phase is canonical
