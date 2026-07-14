from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


BOT_DIR = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "scan_reentrant_delegate_repair_under_test",
        BOT_DIR / "scan_reentrant_delegate_repair_patch.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_active_scan_reentry_continues_to_leaf_wrapper_target(monkeypatch):
    module = _load()

    def leaf(self=None):
        return "scanned"

    def legacy_wrapper(self=None):
        return "wrapper"

    legacy_wrapper.__wrapped__ = leaf

    def original_unwrap(func):
        return func, 0, False

    target = SimpleNamespace(_unwrap_known=original_unwrap)
    assert module._patch_module(target) is True

    def run_scan_phase():
        return target._unwrap_known(legacy_wrapper)

    resolved, depth, cycle = run_scan_phase()
    assert resolved is leaf
    assert depth == 1
    assert cycle is False


def test_install_time_unwrap_remains_strict_and_unchanged():
    module = _load()

    def leaf():
        return None

    def legacy_wrapper():
        return None

    legacy_wrapper.__wrapped__ = leaf

    def original_unwrap(func):
        return func, 0, False

    target = SimpleNamespace(_unwrap_known=original_unwrap)
    module._patch_module(target)

    def install_path():
        return target._unwrap_known(legacy_wrapper)

    resolved, depth, cycle = install_path()
    assert resolved is legacy_wrapper
    assert depth == 0
    assert cycle is False


def test_closure_held_original_is_recovered():
    module = _load()

    def leaf(self=None):
        return "leaf"

    original_run_scan_phase = leaf

    def legacy_wrapper(self=None):
        return original_run_scan_phase(self)

    resolved, depth, cycle = module._unwrap_delegate(legacy_wrapper)
    assert resolved is leaf
    assert depth == 1
    assert cycle is False
