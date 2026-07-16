from __future__ import annotations

from types import ModuleType

from bot import runtime_patch_quiescence_guard_patch as guard


def test_chain_marker_detection_reaches_inner_wrapper():
    def base():
        return None

    base._nija_scan_wrapper_release = "20260714a"  # type: ignore[attr-defined]

    def outer():
        return base()

    outer.__wrapped__ = base  # type: ignore[attr-defined]

    assert guard._chain_has(outer, "_nija_scan_wrapper_release", "20260714a")


def test_legacy_core_patcher_is_suppressed_when_canonical_owner_exists():
    core = ModuleType("bot.nija_core_loop")

    class NijaCoreLoop:
        def run_scan_phase(self):
            return "ok"

    NijaCoreLoop.run_scan_phase._nija_scan_wrapper_release = "20260714a"  # type: ignore[attr-defined]
    core.NijaCoreLoop = NijaCoreLoop

    legacy = ModuleType("runtime_convergence_v2_patch")
    calls = []

    def original_patch(target):
        calls.append(target)
        return True

    legacy._patch_core_loop = original_patch
    assert guard._guard_core_patcher(legacy, "_patch_core_loop") is True
    assert legacy._patch_core_loop(core) is False
    assert calls == []
    assert getattr(NijaCoreLoop.run_scan_phase, "_nija_scan_identity_lock_v2", False)
    assert getattr(NijaCoreLoop.run_scan_phase, "_nija_final_result_contract_e", False)


def test_legacy_patcher_still_runs_without_canonical_owner():
    core = ModuleType("bot.nija_core_loop")

    class NijaCoreLoop:
        def run_scan_phase(self):
            return "ok"

    core.NijaCoreLoop = NijaCoreLoop
    legacy = ModuleType("runtime_convergence_v2_patch")
    calls = []

    def original_patch(target):
        calls.append(target)
        return True

    legacy._patch_core_loop = original_patch
    assert guard._guard_core_patcher(legacy, "_patch_core_loop") is True
    assert legacy._patch_core_loop(core) is True
    assert calls == [core]
