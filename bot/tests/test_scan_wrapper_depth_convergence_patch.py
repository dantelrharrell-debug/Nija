from __future__ import annotations

from functools import wraps
from types import ModuleType

import scan_wrapper_depth_convergence_patch as patch


def _set_origin(func, filename: str):
    func.__code__ = func.__code__.replace(co_filename=filename)
    return func


def _broker_wrapper(base):
    def wrapper(self, *args, **kwargs):
        return base(self, *args, **kwargs)
    setattr(wrapper, patch._BROKER_ATTR, True)
    wrapper.__wrapped__ = base
    return _set_origin(wrapper, f"/app/bot/{patch._BROKER_OWNER_FILE}")


def _canonical_wrapper(base):
    def wrapper(self, *args, **kwargs):
        return base(self, *args, **kwargs)
    setattr(wrapper, patch._CANONICAL_RELEASE_ATTR, "20260714a")
    wrapper.__wrapped__ = base
    return _set_origin(wrapper, f"/app/{patch._CANONICAL_OWNER_FILE}")


def test_inspect_chain_counts_single_broker_and_canonical_layers():
    def leaf(self, *args, **kwargs):
        return "ok"

    chain = _canonical_wrapper(_broker_wrapper(leaf))
    status = patch.inspect_chain(chain)

    assert status["depth"] == 2
    assert status["broker_layers"] == 1
    assert status["canonical_layers"] == 1
    assert status["raw_broker_markers"] == 1
    assert status["raw_canonical_markers"] == 1
    assert status["cycle"] is False


def test_inspect_chain_detects_duplicate_broker_layers():
    def leaf(self, *args, **kwargs):
        return "ok"

    chain = _canonical_wrapper(_broker_wrapper(_broker_wrapper(leaf)))
    status = patch.inspect_chain(chain)

    assert status["broker_layers"] == 2


def test_inspect_chain_ignores_markers_copied_by_wraps():
    def leaf(self, *args, **kwargs):
        return "ok"

    canonical = _canonical_wrapper(_broker_wrapper(leaf))

    @wraps(canonical)
    def outer(self, *args, **kwargs):
        return canonical(self, *args, **kwargs)

    outer.__wrapped__ = canonical
    status = patch.inspect_chain(outer)

    # wraps copies the direct wrapped function's marker dictionary. The outer
    # function therefore repeats the canonical marker, while the deeper broker
    # marker remains present only on the broker wrapper that actually owns it.
    assert status["raw_broker_markers"] == 1
    assert status["raw_canonical_markers"] == 2
    assert status["broker_layers"] == 1
    assert status["canonical_layers"] == 1


def test_inspect_chain_follows_legacy_closure_original():
    def leaf(self, *args, **kwargs):
        return "ok"

    original = leaf

    def legacy(self, *args, **kwargs):
        return original(self, *args, **kwargs)

    setattr(legacy, patch._BROKER_ATTR, True)
    _set_origin(legacy, f"/app/bot/{patch._BROKER_OWNER_FILE}")
    status = patch.inspect_chain(legacy)

    assert status["depth"] == 1
    assert status["broker_layers"] == 1
    assert status["tail"].endswith("leaf")


def test_guarded_installer_does_not_rewrap_when_marker_is_below_outer_owner(monkeypatch):
    calls = []

    def leaf(self, *args, **kwargs):
        return "ok"

    broker = _broker_wrapper(leaf)
    outer = _canonical_wrapper(broker)

    core = ModuleType("bot.nija_core_loop")
    core.NijaCoreLoop = type("NijaCoreLoop", (), {"run_scan_phase": outer})

    module = ModuleType("bot.broker_independent_live_execution_patch")

    def legacy_patch(core_module):
        calls.append(core_module)
        previous = core_module.NijaCoreLoop.run_scan_phase
        core_module.NijaCoreLoop.run_scan_phase = _broker_wrapper(previous)
        return True

    module._patch_core_loop_module = legacy_patch
    module._PATCHED = False

    assert patch._guard_broker_module(module) is True
    assert module._patch_core_loop_module(core) is True
    assert calls == []
    assert module._PATCHED is True
    assert core.NijaCoreLoop.run_scan_phase is outer


def test_guarded_installer_repairs_wrapped_link_on_new_layer():
    def leaf(self, *args, **kwargs):
        return "ok"

    core = ModuleType("bot.nija_core_loop")
    core.NijaCoreLoop = type("NijaCoreLoop", (), {"run_scan_phase": leaf})

    module = ModuleType("bot.broker_independent_live_execution_patch")

    def legacy_patch(core_module):
        previous = core_module.NijaCoreLoop.run_scan_phase

        def broker(self, *args, **kwargs):
            return previous(self, *args, **kwargs)

        setattr(broker, patch._BROKER_ATTR, True)
        _set_origin(broker, f"/app/bot/{patch._BROKER_OWNER_FILE}")
        core_module.NijaCoreLoop.run_scan_phase = broker
        return True

    module._patch_core_loop_module = legacy_patch
    module._PATCHED = False

    patch._guard_broker_module(module)
    assert module._patch_core_loop_module(core) is True
    installed = core.NijaCoreLoop.run_scan_phase
    assert installed.__wrapped__ is leaf
    assert patch.inspect_chain(installed)["broker_layers"] == 1


def test_audit_rejects_oversized_or_duplicate_chain(monkeypatch):
    def leaf(self, *args, **kwargs):
        return "ok"

    chain = _canonical_wrapper(_broker_wrapper(_broker_wrapper(leaf)))
    core = ModuleType("bot.nija_core_loop")
    core.NijaCoreLoop = type("NijaCoreLoop", (), {"run_scan_phase": chain})
    monkeypatch.setitem(patch.sys.modules, "bot.nija_core_loop", core)
    monkeypatch.delitem(patch.sys.modules, "nija_core_loop", raising=False)
    monkeypatch.setattr(patch, "_patch_loaded_broker_modules", lambda: True)

    ready, details = patch.audit()

    assert ready is False
    assert "broker_layers=2" in details["scan_chain"]
    assert patch.os.environ["NIJA_SCAN_WRAPPER_DEPTH_READY"] == "0"
