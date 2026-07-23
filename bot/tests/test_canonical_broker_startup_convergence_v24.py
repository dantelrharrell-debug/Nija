from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "bot" / "canonical_broker_startup_convergence_v24.py"
LOGGING_GUARD_PATH = ROOT / "bot" / "logging_format_guard_patch.py"


def _load_module():
    name = "canonical_broker_startup_convergence_v24_test"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _clear_runtime(monkeypatch):
    for name in (
        "LIVE_TRADING",
        "LIVE_CAPITAL_VERIFIED",
        "NIJA_EXECUTION_ACTIVE",
        "NIJA_RUNTIME_TRADING_STATE",
        "DRY_RUN_MODE",
        "PAPER_MODE",
        "NIJA_WRITER_FENCING_TOKEN",
        "NIJA_WRITER_LEASE_GENERATION",
        "NIJA_WRITER_LEASE_ACQUIRED",
        "NIJA_PREBOT_WRITER_AUTHORITY_READY",
        "NIJA_CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_READY",
    ):
        monkeypatch.delenv(name, raising=False)


def _load_logging_guard(monkeypatch):
    _clear_runtime(monkeypatch)
    name = "logging_format_guard_v24_test"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, LOGGING_GUARD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_loader_imports_importlib_util_explicitly():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "import importlib.util" in source
    module = _load_module()
    assert module.importlib.util is importlib.util


def test_writer_lineage_requires_token_generation_and_lease(monkeypatch):
    module = _load_module()
    _clear_runtime(monkeypatch)

    assert module._writer_lineage() == (False, "fencing_token_missing")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token")
    assert module._writer_lineage() == (False, "lease_generation_missing")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "42")
    assert module._writer_lineage() == (False, "lease_not_acquired")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    assert module._writer_lineage() == (True, "lineage_ready generation=42")


def test_self_healing_live_path_prepares_manager_before_original(monkeypatch):
    module = _load_module()
    _clear_runtime(monkeypatch)
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "43")
    monkeypatch.setenv("NIJA_PREBOT_WRITER_AUTHORITY_READY", "1")

    calls: list[str] = []

    class SelfHealingStartup:
        def run(self):
            calls.append("original")
            return "ok"

    fake = ModuleType("bot.self_healing_startup")
    fake.SelfHealingStartup = SelfHealingStartup
    monkeypatch.setattr(
        module,
        "_prepare_canonical_manager",
        lambda: calls.append("prepare") or SimpleNamespace(_fsm_initialized=True),
    )

    assert module._patch_self_healing_module(fake) is True
    assert SelfHealingStartup().run() == "ok"
    assert calls == ["prepare", "original"]


def test_self_healing_live_path_fails_closed_without_lineage(monkeypatch):
    module = _load_module()
    _clear_runtime(monkeypatch)
    monkeypatch.setenv("LIVE_TRADING", "true")
    called = False

    class SelfHealingStartup:
        def run(self):
            nonlocal called
            called = True
            return "unsafe"

    fake = ModuleType("self_healing_startup")
    fake.SelfHealingStartup = SelfHealingStartup
    assert module._patch_self_healing_module(fake) is True

    with pytest.raises(RuntimeError, match="fencing_token_missing"):
        SelfHealingStartup().run()
    assert called is False
    assert (
        module.os.environ["NIJA_CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_READY"]
        == "0"
    )


def test_self_healing_non_live_path_does_not_prepare_manager(monkeypatch):
    module = _load_module()
    _clear_runtime(monkeypatch)
    monkeypatch.setenv("DRY_RUN_MODE", "true")
    calls: list[str] = []

    class SelfHealingStartup:
        def run(self):
            calls.append("original")
            return "dry"

    fake = ModuleType("bot.self_healing_startup")
    fake.SelfHealingStartup = SelfHealingStartup
    monkeypatch.setattr(
        module,
        "_prepare_canonical_manager",
        lambda: calls.append("prepare"),
    )

    assert module._patch_self_healing_module(fake) is True
    assert SelfHealingStartup().run() == "dry"
    assert calls == ["original"]


def test_bot_main_patch_delegates_to_v22_guards(monkeypatch):
    module = _load_module()
    calls: list[str] = []
    v22 = SimpleNamespace(
        _patch_writer_acquire=lambda target: calls.append("acquire") or True,
        _patch_main=lambda target: calls.append("main") or True,
    )
    monkeypatch.setattr(module, "_load_v22_module", lambda: v22)
    fake = ModuleType("bot.bot_main")

    assert module._patch_bot_main_module(fake) is True
    assert calls == ["acquire", "main"]
    assert module._patch_bot_main_module(fake) is True
    assert calls == ["acquire", "main"]


def test_logging_guard_live_intent_accepts_supported_aliases(monkeypatch):
    guard = _load_logging_guard(monkeypatch)

    monkeypatch.setenv("LIVE_TRADING", "true")
    assert guard._live_intent() is True
    monkeypatch.delenv("LIVE_TRADING")
    monkeypatch.setenv("NIJA_EXECUTION_ACTIVE", "1")
    assert guard._live_intent() is True
    monkeypatch.setenv("PAPER_MODE", "true")
    assert guard._live_intent() is False


def test_live_trading_installer_failure_is_not_swallowed(monkeypatch):
    guard = _load_logging_guard(monkeypatch)
    monkeypatch.setenv("LIVE_TRADING", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setattr(
        guard.importlib.util, "spec_from_file_location", lambda *args, **kwargs: None
    )
    guard.sys.modules.pop("nija_canonical_broker_startup_convergence_v24", None)

    with pytest.raises(RuntimeError, match="could not load spec"):
        guard._install_canonical_broker_startup_convergence()


def test_non_live_installer_failure_remains_diagnostic_only(monkeypatch):
    guard = _load_logging_guard(monkeypatch)
    monkeypatch.setenv("DRY_RUN_MODE", "true")
    monkeypatch.setattr(
        guard.importlib.util, "spec_from_file_location", lambda *args, **kwargs: None
    )
    guard.sys.modules.pop("nija_canonical_broker_startup_convergence_v24", None)

    guard._install_canonical_broker_startup_convergence()
