from __future__ import annotations

import importlib.util
import threading
from pathlib import Path
from types import SimpleNamespace


BOT_DIR = Path(__file__).resolve().parents[1]


def _load_patch():
    spec = importlib.util.spec_from_file_location(
        "stale_renewal_recovery_v40_patch_under_test",
        BOT_DIR / "stale_renewal_recovery_v40_patch.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_watchdog_rotates_when_writer_generation_changes() -> None:
    patch = _load_patch()
    runtime = SimpleNamespace(
        _generation=41,
        acquired=False,
        lost=False,
    )

    assert patch._start_watchdog(runtime)
    old_thread = getattr(runtime, patch._WATCHDOG_ATTR)
    assert getattr(old_thread, patch._WATCHDOG_GENERATION_ATTR) == 41

    runtime._generation = 42
    assert patch._start_watchdog(runtime)
    new_thread = getattr(runtime, patch._WATCHDOG_ATTR)
    assert new_thread is not old_thread
    assert getattr(new_thread, patch._WATCHDOG_GENERATION_ATTR) == 42

    getattr(runtime, patch._WATCHDOG_STOP_ATTR).set()
    new_thread.join(timeout=3.0)
    old_thread.join(timeout=3.0)
    assert not old_thread.is_alive()
    assert not new_thread.is_alive()


def test_stale_epoch_exits_before_fail_closed_mutation(monkeypatch) -> None:
    patch = _load_patch()
    health_entered = threading.Event()
    health_release = threading.Event()

    def blocked_health(_runtime):
        health_entered.set()
        health_release.wait(timeout=2.0)
        return False, "renewal_success_stale", 30.0, 15.0

    runtime = SimpleNamespace(
        _generation=7,
        acquired=True,
        lost=False,
    )
    monkeypatch.setattr(patch, "_runtime_health", blocked_health)
    monkeypatch.setattr(patch, "_cfg_float", lambda *_args: 0.25)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_EXECUTION_ACTIVE", "true")

    stop = threading.Event()
    thread = threading.Thread(target=patch._watchdog_loop, args=(runtime, stop), daemon=True)
    thread.start()
    assert health_entered.wait(timeout=1.0)
    runtime._generation = 8
    health_release.set()
    thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert patch.os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "1"
    assert patch.os.environ["NIJA_EXECUTION_ACTIVE"] == "true"
