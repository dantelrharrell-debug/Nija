from __future__ import annotations

from types import ModuleType, SimpleNamespace

import scan_owner_okx_auth_convergence_patch as scan_owner
import scan_wrapper_convergence_repair_patch as convergence


def _result(scored: int = 1):
    return SimpleNamespace(
        symbols_scored=scored,
        entries_taken=0,
        entries_blocked=0,
        exits_taken=0,
        next_interval=15,
        errors=[],
        metadata={},
    )


def _module_with_broker_slot_wrapper():
    calls: list[str] = []

    def base(self, *args, **kwargs):
        broker = kwargs.get("broker") or (args[0] if args else None)
        calls.append(str(getattr(broker, "account_id", "platform")))
        return _result(9)

    original_run_scan_phase = base

    def broker_slot_wrapper(self, *args, **kwargs):
        return original_run_scan_phase(self, *args, **kwargs)

    broker_slot_wrapper._nija_broker_slot_scoped = True

    class NijaCoreLoop:
        run_scan_phase = broker_slot_wrapper

    module = ModuleType("bot.nija_core_loop")
    module.NijaCoreLoop = NijaCoreLoop
    return module, calls


def test_scan_owner_respects_existing_canonical_owner():
    module, calls = _module_with_broker_slot_wrapper()

    assert convergence._patch_core_loop(module) is True
    canonical = module.NijaCoreLoop.run_scan_phase
    assert getattr(canonical, "_nija_scan_wrapper_canonical_v2", False)
    assert convergence._guard_secondary_scan_owner() is True

    # The auth convergence watchdog must not install a second account owner.
    assert scan_owner._patch_core(module) is True
    assert module.NijaCoreLoop.run_scan_phase is canonical

    loop = module.NijaCoreLoop()
    for account_id in ("platform", "daivon_frazier", "tania_gilbert"):
        broker = SimpleNamespace(account_id=account_id, broker_name="kraken")
        result = loop.run_scan_phase(broker=broker)
        assert result.symbols_scored == 9
        assert result.entries_blocked == 0

    assert calls == ["platform", "daivon_frazier", "tania_gilbert"]


def test_scan_wrapper_recognizes_scan_owner_wrapper_as_known_layer():
    def base(self, *args, **kwargs):
        return _result(4)

    def owner_wrapper(self, *args, **kwargs):
        return base(self, *args, **kwargs)

    owner_wrapper._nija_scan_owner_result_reuse_20260713b = True
    owner_wrapper.__wrapped__ = base

    assert convergence._is_known_wrapper(owner_wrapper) is True
    resolved, depth, cycle = convergence._unwrap_known(owner_wrapper)
    assert resolved is base
    assert depth == 1
    assert cycle is False


def test_repeated_watchdogs_do_not_oscillate_method_identity():
    module, _ = _module_with_broker_slot_wrapper()
    assert convergence._patch_core_loop(module) is True
    canonical = module.NijaCoreLoop.run_scan_phase
    assert convergence._guard_secondary_scan_owner() is True

    for _ in range(10):
        assert scan_owner._patch_core(module) is True
        assert module.NijaCoreLoop.run_scan_phase is canonical
        # Already canonical for this release: no replacement should occur.
        assert convergence._patch_core_loop(module) is False
        assert module.NijaCoreLoop.run_scan_phase is canonical
