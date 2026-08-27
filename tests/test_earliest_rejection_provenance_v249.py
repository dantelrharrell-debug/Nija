"""Regression coverage for earliest rejection-provenance startup barriers."""

from __future__ import annotations

import builtins
from pathlib import Path
from types import SimpleNamespace


SANITIZER = Path(__file__).resolve().parents[1] / "bot" / "strict_live_startup_sanitizer.py"


def _load_sanitizer_without_autorun(fake_import):
    """Execute sanitizer definitions without running its module-import hook."""
    source = SANITIZER.read_text(encoding="utf-8")
    source = source.split("# This must run before sanitize imports", 1)[0]

    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("bot."):
            return fake_import(name, fromlist)
        return real_import(name, globals, locals, fromlist, level)

    namespace = {
        "__name__": "nija_test_strict_live_startup_sanitizer_v250",
        "__builtins__": dict(vars(builtins), __import__=guarded_import),
    }
    exec(compile(source, str(SANITIZER), "exec"), namespace)
    return namespace


def test_v217_v228_v224_precede_every_remaining_early_repair(monkeypatch):
    calls = []

    def fake_import(name, _fromlist):
        calls.append(name)
        return SimpleNamespace(install_import_hook=lambda: True)

    ns = _load_sanitizer_without_autorun(fake_import)
    monkeypatch.delenv("NIJA_EARLY_SAFETY_REPAIRS_READY", raising=False)

    assert ns["_install_early_safety_repairs"]() is True
    assert calls[:3] == [
        "bot.kill_switch_early_provenance_v217_patch",
        "bot.exchange_reject_dispatch_provenance_v228_patch",
        "bot.exchange_reject_provenance_v224_patch",
    ]
    assert calls[3:] == [
        f"bot.{module_name}" for module_name, _label in ns["_REMAINING_EARLY_REPAIRS"]
    ]
    assert ns["os"].environ["NIJA_EARLY_SAFETY_REPAIRS_READY"] == "1"


def test_v228_failure_blocks_v224_and_all_downstream_early_imports(monkeypatch):
    calls = []

    def fake_import(name, _fromlist):
        calls.append(name)
        if name == "bot.exchange_reject_dispatch_provenance_v228_patch":
            return SimpleNamespace(install_import_hook=lambda: False)
        return SimpleNamespace(install_import_hook=lambda: True)

    ns = _load_sanitizer_without_autorun(fake_import)
    monkeypatch.delenv("NIJA_EARLY_SAFETY_REPAIRS_READY", raising=False)

    assert ns["_install_early_safety_repairs"]() is False
    assert calls == [
        "bot.kill_switch_early_provenance_v217_patch",
        "bot.exchange_reject_dispatch_provenance_v228_patch",
    ]
    assert "bot.exchange_reject_provenance_v224_patch" not in calls
    assert ns["os"].environ["NIJA_EARLY_SAFETY_REPAIRS_READY"] == "0"


def test_v224_failure_blocks_all_downstream_early_imports(monkeypatch):
    calls = []

    def fake_import(name, _fromlist):
        calls.append(name)
        if name == "bot.exchange_reject_provenance_v224_patch":
            return SimpleNamespace(install_import_hook=lambda: False)
        return SimpleNamespace(install_import_hook=lambda: True)

    ns = _load_sanitizer_without_autorun(fake_import)
    monkeypatch.delenv("NIJA_EARLY_SAFETY_REPAIRS_READY", raising=False)

    assert ns["_install_early_safety_repairs"]() is False
    assert calls == [
        "bot.kill_switch_early_provenance_v217_patch",
        "bot.exchange_reject_dispatch_provenance_v228_patch",
        "bot.exchange_reject_provenance_v224_patch",
    ]
    assert not any(
        name == f"bot.{module_name}"
        for module_name, _label in ns["_REMAINING_EARLY_REPAIRS"]
        for name in calls
    )
    assert ns["os"].environ["NIJA_EARLY_SAFETY_REPAIRS_READY"] == "0"


def test_v217_failure_prevents_pipeline_import_and_remains_fail_closed(monkeypatch):
    calls = []

    def fake_import(name, _fromlist):
        calls.append(name)
        if name == "bot.kill_switch_early_provenance_v217_patch":
            return SimpleNamespace(install_import_hook=lambda: False)
        return SimpleNamespace(install_import_hook=lambda: True)

    ns = _load_sanitizer_without_autorun(fake_import)
    monkeypatch.delenv("NIJA_EARLY_SAFETY_REPAIRS_READY", raising=False)

    assert ns["_install_early_safety_repairs"]() is False
    assert calls == ["bot.kill_switch_early_provenance_v217_patch"]
    assert "bot.exchange_reject_dispatch_provenance_v228_patch" not in calls
    assert "bot.exchange_reject_provenance_v224_patch" not in calls
    assert ns["os"].environ["NIJA_EARLY_SAFETY_REPAIRS_READY"] == "0"


def test_no_rejection_window_or_force_activation_mutation_is_introduced():
    source = SANITIZER.read_text(encoding="utf-8")

    forbidden = (
        "clear_rejection_window(",
        "deactivate_kill_switch(",
        "force_live(",
        "grant_execution_authority(",
        "NIJA_FORCE_ACTIVATION\"] = \"true\"",
    )
    assert all(token not in source for token in forbidden)
    assert "rejection_window_cleared=false" in source
    assert "kill_switch_unchanged=true" in source
    assert "forced_activation=false" in source
    assert "safety_gates_bypassed=false" in source
    assert "synthetic_stop_provenance_v224=true" in source
