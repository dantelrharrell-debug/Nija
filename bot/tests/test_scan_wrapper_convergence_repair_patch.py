import importlib
import sys
import types


def _reload():
    module = importlib.import_module("scan_wrapper_convergence_repair_patch")
    return importlib.reload(module)


def test_known_wrapper_chain_is_collapsed_to_original():
    module = _reload()

    class Result:
        symbols_scored = 3
        entries_taken = 1
        entries_blocked = 0
        exits_taken = 0
        next_interval = 30

    def base(self, *args, **kwargs):
        return Result()

    def legacy_one(self, *args, **kwargs):
        return base(self, *args, **kwargs)

    legacy_one._nija_account_scan_serialized_e = True
    legacy_one.__wrapped__ = base

    def legacy_two(self, *args, **kwargs):
        return legacy_one(self, *args, **kwargs)

    legacy_two._nija_final_result_contract_e = True
    legacy_two.__wrapped__ = legacy_one

    class NijaCoreLoop:
        run_scan_phase = legacy_two

    fake = types.ModuleType("bot.nija_core_loop")
    fake.NijaCoreLoop = NijaCoreLoop
    assert module._patch_core_loop(fake) is True
    patched = NijaCoreLoop.run_scan_phase
    assert patched._nija_scan_wrapper_canonical_h is True
    assert patched._nija_account_scan_serialized_e is True
    assert patched._nija_final_result_contract_e is True
    assert patched.__wrapped__ is base
    result = NijaCoreLoop().run_scan_phase(None)
    assert result.symbols_scored == 3
    assert result.entries_taken == 1


def test_duplicate_scan_returns_result_contract():
    module = _reload()
    result = module._coerce_result(None)
    assert result.symbols_scored == 0
    assert result.entries_taken == 0
    assert result.entries_blocked == 1
    assert result.exits_taken == 0
    assert result.next_interval >= 5


def test_tuple_is_coerced_to_result_contract():
    module = _reload()
    result = module._coerce_result((4, 2, 1, {"exits_taken": 3, "next_interval": 20}))
    assert result.symbols_scored == 4
    assert result.entries_blocked == 2
    assert result.entries_taken == 1
    assert result.exits_taken == 3
    assert result.next_interval == 20


def test_legacy_watchdogs_recognize_canonical_wrapper():
    module = _reload()

    def base(self):
        return None

    def canonical(self):
        return base(self)

    canonical._nija_scan_wrapper_canonical_h = True
    canonical._nija_account_scan_serialized_e = True
    canonical._nija_final_result_contract_e = True
    canonical.__wrapped__ = base

    assert module._is_known_wrapper(canonical) is True
    resolved, depth, cycle = module._unwrap_known(canonical)
    assert resolved is base
    assert depth == 1
    assert cycle is False


def test_patch_core_loop_does_not_add_second_canonical_owner_under_outer_wrapper():
    module = _reload()

    def base(self):
        return "ok"

    def canonical(self):
        return base(self)

    canonical._nija_scan_wrapper_release = module._MARKER
    canonical._nija_scan_wrapper_canonical_h = True
    canonical.__wrapped__ = base

    def outer(self):
        return canonical(self)

    outer.__wrapped__ = canonical

    class NijaCoreLoop:
        run_scan_phase = outer

    fake = types.ModuleType("bot.nija_core_loop")
    fake.NijaCoreLoop = NijaCoreLoop

    assert module._patch_core_loop(fake) is False
    assert NijaCoreLoop.run_scan_phase is outer
    assert module._chain_has_current_owner(outer) is True


def test_bootstrap_installs_canonical_repair_after_legacy_scan_patches(monkeypatch):
    bootstrap = importlib.import_module("source_runtime_guard_bootstrap")
    bootstrap = importlib.reload(bootstrap)
    order = []

    def fake_install(name):
        order.append(name)

    monkeypatch.setattr(bootstrap, "_install_required", fake_install)
    monkeypatch.setattr(bootstrap, "_deployment_commit", lambda: "test")
    assert bootstrap.install() is True
    assert order.index("scan_wrapper_convergence_repair_patch") > order.index("final_runtime_convergence_patch")
    assert order.index("scan_wrapper_convergence_repair_patch") > order.index("runtime_convergence_hardening_patch")
    assert bootstrap.installed_marker() == "20260712h"
