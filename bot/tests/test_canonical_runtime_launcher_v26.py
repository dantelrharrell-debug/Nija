from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "canonical_runtime_launcher_v26.py"
PATCHER = ROOT / "scripts" / "apply_canonical_launcher_v26.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_start_script_patch_is_idempotent_and_removes_direct_main_launch() -> None:
    patcher = _load("test_apply_canonical_launcher_v26", PATCHER)
    source = "set +e\n$PY -u main.py\nstatus=$?\n"
    once = patcher.patch_text(source)
    twice = patcher.patch_text(once)
    assert once == twice
    assert "$PY -u scripts/canonical_runtime_launcher_v26.py" in once
    assert "$PY -u main.py" not in once


def test_launcher_installs_v24_before_bot_main_import(monkeypatch) -> None:
    launcher = _load("test_canonical_runtime_launcher_v26", LAUNCHER)
    sys.modules.pop("bot.bot_main", None)
    monkeypatch.delenv("NIJA_CANONICAL_RUNTIME_LAUNCHER_V26_READY", raising=False)
    monkeypatch.delenv(
        "NIJA_CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_INSTALLED", raising=False
    )

    module = launcher.install_canonical_startup_guard()

    assert module is not None
    assert "bot.bot_main" not in sys.modules
    assert os.environ["NIJA_CANONICAL_RUNTIME_LAUNCHER_V26_READY"] == "1"
    assert (
        os.environ["NIJA_CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_INSTALLED"]
        == "1"
    )


def test_launcher_rejects_late_install(monkeypatch) -> None:
    launcher = _load("test_canonical_runtime_launcher_v26_late", LAUNCHER)
    monkeypatch.setitem(sys.modules, "bot.bot_main", object())
    try:
        launcher.install_canonical_startup_guard()
    except RuntimeError as exc:
        assert "loaded before canonical launcher guard" in str(exc)
    else:
        raise AssertionError("late canonical guard installation must fail closed")
