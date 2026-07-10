from __future__ import annotations

import builtins
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

import source_runtime_guard_bootstrap as source_bootstrap


def _reset_source_bootstrap(monkeypatch) -> None:
    monkeypatch.setattr(source_bootstrap, "_INSTALLED", False)
    monkeypatch.delenv("NIJA_VENUE_READINESS_SOURCE_BOOTSTRAP", raising=False)
    monkeypatch.delenv("NIJA_VENUE_READINESS_SOURCE_MARKER", raising=False)


def test_source_bootstrap_installs_venue_repair_once_and_records_commit(monkeypatch):
    _reset_source_bootstrap(monkeypatch)
    calls: list[str] = []
    fake_repair = ModuleType("venue_readiness_execution_repair_patch")
    fake_repair.install = lambda: calls.append("install")

    real_import = source_bootstrap.importlib.import_module

    def _fake_import(name: str):
        if name == "venue_readiness_execution_repair_patch":
            return fake_repair
        return real_import(name)

    monkeypatch.setattr(source_bootstrap.importlib, "import_module", _fake_import)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc123")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    assert source_bootstrap.install() is True
    assert source_bootstrap.install() is True
    assert calls == ["install"]
    assert source_bootstrap.installed_marker() == "20260710af"
    assert source_bootstrap.os.environ["NIJA_VENUE_READINESS_SOURCE_BOOTSTRAP"] == "1"


def test_source_bootstrap_live_failure_raises_system_exit(monkeypatch):
    _reset_source_bootstrap(monkeypatch)
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    def _broken_import(_name: str):
        raise ImportError("repair missing")

    monkeypatch.setattr(source_bootstrap.importlib, "import_module", _broken_import)

    with pytest.raises(SystemExit) as exc_info:
        source_bootstrap.install()

    assert exc_info.value.code == 78
    assert source_bootstrap.os.environ["NIJA_VENUE_READINESS_SOURCE_BOOTSTRAP"] == "0"


def test_global_startup_guards_install_source_repair_before_other_guards(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    path = root / "bot" / "global_runtime_startup_guards.py"
    spec = importlib.util.spec_from_file_location("nija_test_global_runtime_startup_guards", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    order: list[str] = []
    fake_source = ModuleType("source_runtime_guard_bootstrap")
    fake_source.install = lambda: order.append("source") or True

    real_import = module.importlib.import_module

    def _fake_import(name: str):
        if name == "source_runtime_guard_bootstrap":
            return fake_source
        return real_import(name)

    monkeypatch.setattr(module.importlib, "import_module", _fake_import)
    monkeypatch.setattr(module, "_set_defaults", lambda: order.append("defaults"))
    monkeypatch.setattr(module, "_install_kraken_patch_log_dedupe", lambda: order.append("dedupe"))
    monkeypatch.setattr(
        module,
        "_install_module",
        lambda module_name, marker: order.append(module_name) or True,
    )
    monkeypatch.delattr(
        builtins,
        "_NIJA_GLOBAL_RUNTIME_STARTUP_GUARDS_20260706B",
        raising=False,
    )

    module.install()

    assert order[0] == "source"
    assert order[1] == "defaults"
    assert "held_trade_cap_guard_patch" in order
