from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType


ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "bot" / "writer_runtime_core_thread_backstop_v56_patch.py"
BOT_ENTRYPOINT = ROOT / "bot" / "bot.py"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PATCH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _Thread:
    def __init__(self, alive: bool) -> None:
        self.alive = alive

    def is_alive(self) -> bool:
        return self.alive


def _install_entrypoint(monkeypatch, thread) -> None:
    runtime = type("Runtime", (), {})()
    runtime._core_thread = thread
    entrypoint = ModuleType("bot.entrypoint_writer_authority")
    entrypoint.get_entrypoint_writer_authority = lambda: runtime
    monkeypatch.setitem(sys.modules, "bot.entrypoint_writer_authority", entrypoint)


def test_writer_registered_core_thread_is_seen_by_v54(monkeypatch) -> None:
    v56 = _load("test_writer_runtime_v56_registered_core")

    bot_main = ModuleType("bot.bot_main")
    bot_main._core_loop_thread = None
    monkeypatch.setitem(sys.modules, "bot.bot_main", bot_main)
    _install_entrypoint(monkeypatch, _Thread(True))

    v54 = ModuleType("bot.writer_runtime_lifecycle_supervisor_v54_patch")
    v54._core_thread_alive = lambda module=None: False
    monkeypatch.setitem(sys.modules, "bot.writer_runtime_lifecycle_supervisor_v54_patch", v54)

    assert v56.install_import_hook() is True
    assert v54._core_thread_alive(bot_main) is True


def test_bot_main_core_thread_remains_authoritative(monkeypatch) -> None:
    v56 = _load("test_writer_runtime_v56_bot_main_core")

    bot_main = ModuleType("bot.bot_main")
    bot_main._core_loop_thread = _Thread(True)
    monkeypatch.setitem(sys.modules, "bot.bot_main", bot_main)
    _install_entrypoint(monkeypatch, None)

    assert v56._canonical_core_thread_alive(bot_main) is True


def test_no_live_core_thread_returns_false(monkeypatch) -> None:
    v56 = _load("test_writer_runtime_v56_no_core")

    bot_main = ModuleType("bot.bot_main")
    bot_main._core_loop_thread = _Thread(False)
    monkeypatch.setitem(sys.modules, "bot.bot_main", bot_main)
    _install_entrypoint(monkeypatch, _Thread(False))

    assert v56._canonical_core_thread_alive(bot_main) is False


def test_canonical_fast_path_installs_v56() -> None:
    source = BOT_ENTRYPOINT.read_text(encoding="utf-8")
    fast_block = source.split("_FAST_PATH_INSTALLERS = (", 1)[1].split(
        ")\n\n_LEGACY_INSTALLERS", 1
    )[0]

    assert "writer_runtime_core_thread_backstop_v56_patch" in fast_block
    assert "WRITER_RUNTIME_CORE_THREAD_BACKSTOP_V56" in fast_block
