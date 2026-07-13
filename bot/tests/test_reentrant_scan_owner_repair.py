from __future__ import annotations

from types import ModuleType, SimpleNamespace

import reentrant_scan_owner_repair as repair


def _result(scored: int = 5):
    return SimpleNamespace(
        symbols_scored=scored,
        entries_taken=0,
        entries_blocked=0,
        exits_taken=0,
        next_interval=15,
        errors=[],
    )


def test_faulty_scan_owner_wrapper_is_removed_and_not_reinstalled():
    module = ModuleType("bot.nija_core_loop")

    class NijaCoreLoop:
        def run_scan_phase(self, *args, **kwargs):
            return _result(9)

    canonical = NijaCoreLoop.run_scan_phase

    def faulty(self, *args, **kwargs):
        return SimpleNamespace(
            symbols_scored=0,
            entries_taken=0,
            entries_blocked=1,
            exits_taken=0,
            next_interval=15,
            errors=["reentrant_scan"],
        )

    faulty._nija_scan_owner_result_reuse_20260713b = True
    faulty.__wrapped__ = canonical
    NijaCoreLoop.run_scan_phase = faulty
    module.NijaCoreLoop = NijaCoreLoop

    assert repair._repair_module(module) is True
    assert NijaCoreLoop.run_scan_phase is canonical
    assert getattr(canonical, "_nija_scan_owner_result_reuse_20260713b", False) is True
    assert getattr(canonical, "_nija_reentrant_scan_owner_repair_20260713c", False) is True
    assert NijaCoreLoop().run_scan_phase().symbols_scored == 9
