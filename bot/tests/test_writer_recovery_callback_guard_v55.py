from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import threading
from types import ModuleType


ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "bot" / "writer_recovery_callback_guard_v55_patch.py"
BOT_ENTRYPOINT = ROOT / "bot" / "bot.py"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PATCH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _install_fake_v39(monkeypatch, started: list[tuple]) -> ModuleType:
    v39 = ModuleType("bot.production_readiness_v39_patch")
    v39._RECOVERY_LOCK = threading.Lock()
    v39._RECOVERY_ACTIVE = False
    v39._recoverable_writer_loss = (
        lambda reason: "lock_missing_and_fencing_token_mismatch" in str(reason)
    )

    def _start_writer_recovery(bot_main, runtime, reason, fallback):
        started.append((bot_main, runtime, reason, fallback))
        with v39._RECOVERY_LOCK:
            v39._RECOVERY_ACTIVE = True
        return True

    v39._start_writer_recovery = _start_writer_recovery
    monkeypatch.setitem(sys.modules, "bot.production_readiness_v39_patch", v39)
    return v39


def _install_fake_bot_main(monkeypatch) -> ModuleType:
    bot_main = ModuleType("bot.bot_main")
    bot_main._shutdown_event = threading.Event()
    bot_main._authority_heartbeat_monitor = None
    monkeypatch.setitem(sys.modules, "bot.bot_main", bot_main)
    return bot_main


def test_recoverable_loss_hands_off_to_v39_once(monkeypatch) -> None:
    v55 = _load("test_writer_recovery_v55_recoverable")
    started: list[tuple] = []
    v39 = _install_fake_v39(monkeypatch, started)
    bot_main = _install_fake_bot_main(monkeypatch)
    generic: list[str] = []

    class Runtime:
        def __init__(self):
            self._lost = threading.Event()
            self._stop = threading.Event()
            self._on_lost_callback = lambda reason: generic.append(reason)

        @property
        def lost(self):
            return self._lost.is_set()

        def set_on_lost_callback(self, callback):
            self._on_lost_callback = callback

        def _mark_lost(self, reason):
            self._lost.set()
            if self._on_lost_callback is not None:
                self._on_lost_callback(reason)

        def release(self):
            self._lost.set()
            return True

    module = ModuleType("bot.entrypoint_writer_authority")
    module.EntrypointWriterAuthority = Runtime
    assert v55._patch_entrypoint_module(module) is True

    runtime = Runtime()
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_EXECUTION_ACTIVE", "true")
    runtime._mark_lost("lock_missing_and_fencing_token_mismatch")

    assert len(started) == 1
    assert started[0][1] is runtime
    assert started[0][2] == "lock_missing_and_fencing_token_mismatch"
    assert generic == []
    assert bot_main._shutdown_event.is_set() is False
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_EXECUTION_ACTIVE"] == "false"
    with v39._RECOVERY_LOCK:
        assert v39._RECOVERY_ACTIVE is True


def test_nonrecoverable_loss_preserves_prior_callback(monkeypatch) -> None:
    v55 = _load("test_writer_recovery_v55_nonrecoverable")
    started: list[tuple] = []
    _install_fake_v39(monkeypatch, started)
    _install_fake_bot_main(monkeypatch)
    generic: list[str] = []

    class Runtime:
        def __init__(self):
            self._lost = threading.Event()
            self._stop = threading.Event()
            self._on_lost_callback = lambda reason: generic.append(reason)

        @property
        def lost(self):
            return self._lost.is_set()

        def set_on_lost_callback(self, callback):
            self._on_lost_callback = callback

        def _mark_lost(self, reason):
            self._lost.set()
            if self._on_lost_callback is not None:
                self._on_lost_callback(reason)

        def release(self):
            return True

    module = ModuleType("bot.entrypoint_writer_authority")
    module.EntrypointWriterAuthority = Runtime
    assert v55._patch_entrypoint_module(module) is True

    runtime = Runtime()
    runtime._mark_lost("lock_owned_by_different_writer")

    assert started == []
    assert generic == ["lock_owned_by_different_writer"]


def test_release_sets_stop_before_existing_release_stack(monkeypatch) -> None:
    v55 = _load("test_writer_recovery_v55_release")

    class Runtime:
        def __init__(self):
            self._lost = threading.Event()
            self._stop = threading.Event()
            self._on_lost_callback = None
            self.stop_seen = False

        @property
        def lost(self):
            return self._lost.is_set()

        def set_on_lost_callback(self, callback):
            self._on_lost_callback = callback

        def _mark_lost(self, reason):
            self._lost.set()

        def release(self):
            self.stop_seen = self._stop.is_set()
            self._lost.set()
            return True

    module = ModuleType("entrypoint_writer_authority")
    module.EntrypointWriterAuthority = Runtime
    assert v55._patch_entrypoint_module(module) is True

    runtime = Runtime()
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_EXECUTION_ACTIVE", "true")

    assert runtime.release() is True
    assert runtime.stop_seen is True
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_EXECUTION_ACTIVE"] == "false"


def test_core_thread_loss_is_never_recoverable(monkeypatch) -> None:
    v55 = _load("test_writer_recovery_v55_core_terminal")
    started: list[tuple] = []
    _install_fake_v39(monkeypatch, started)
    _install_fake_bot_main(monkeypatch)

    assert v55._recoverable(
        "writer_lock_released_for_reelection:core_thread_dead name=core"
    ) is False
    assert started == []


def test_canonical_fast_path_installs_v55() -> None:
    source = BOT_ENTRYPOINT.read_text(encoding="utf-8")
    fast_block = source.split("_FAST_PATH_INSTALLERS = (", 1)[1].split(
        ")\n\n_LEGACY_INSTALLERS", 1
    )[0]

    assert "writer_recovery_callback_guard_v55_patch" in fast_block
    assert "WRITER_RECOVERY_CALLBACK_V55" in fast_block
