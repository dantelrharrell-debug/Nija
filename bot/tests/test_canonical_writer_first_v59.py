from __future__ import annotations

import importlib.util
from pathlib import Path
import runpy
import sys
from types import ModuleType


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "canonical_runtime_launcher_v26.py"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, LAUNCHER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_launcher_orders_writer_before_main_runtime_fanout(monkeypatch, tmp_path) -> None:
    launcher = _load("test_canonical_writer_first_v59_order")
    fake_main = tmp_path / "main.py"
    fake_main.write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "MAIN_PATH", fake_main)

    events: list[str] = []
    bot_entry = ModuleType("bot.bot")
    bot_main = ModuleType("bot.bot_main")

    monkeypatch.setattr(
        launcher,
        "install_canonical_startup_guard",
        lambda: events.append("guards"),
    )

    def _writer_first():
        events.append("writer")
        return bot_entry, bot_main

    def _single_identity(entry, main):
        assert entry is bot_entry
        assert main is bot_main
        events.append("main")

    monkeypatch.setattr(launcher, "_bootstrap_writer_first", _writer_first)
    monkeypatch.setattr(launcher, "_run_main_single_identity", _single_identity)

    assert launcher.main() == 0
    assert events == ["guards", "writer", "main"]


def test_writer_first_requires_exact_distributed_runtime(monkeypatch) -> None:
    launcher = _load("test_canonical_writer_first_v59_exact")
    bot_entry = ModuleType("bot.bot")
    bot_main = ModuleType("bot.bot_main")

    class Runtime:
        acquired = True
        lost = False
        _local_fallback = True

    bot_main._writer_authority_runtime = Runtime()
    bot_main._writer_authority_last_error = ""
    bot_main._acquire_writer_authority_before_nonce = lambda: True
    released: list[bool] = []
    bot_main._release_writer_authority = lambda: released.append(True)

    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "88")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token-88")

    def _import(name: str):
        if name == "bot.bot":
            return bot_entry
        if name == "bot.bot_main":
            return bot_main
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(launcher.importlib, "import_module", _import)

    try:
        launcher._bootstrap_writer_first()
    except RuntimeError as exc:
        assert "exact distributed lineage" in str(exc)
    else:
        raise AssertionError("local fallback must not satisfy writer-first v59")

    assert released == [True]


def test_single_identity_handoff_reuses_bot_module(monkeypatch, tmp_path) -> None:
    launcher = _load("v59_single_identity_test_module")
    fake_main = tmp_path / "main.py"
    fake_main.write_text(
        "import runpy\nrunpy.run_module('bot.bot', run_name='__main__')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher, "MAIN_PATH", fake_main)

    bot_entry = ModuleType("bot.bot")
    bot_main = ModuleType("bot.bot_main")
    calls: list[str] = []

    def _main() -> int:
        calls.append("main")
        return 0

    bot_entry.main = _main
    monkeypatch.setitem(sys.modules, "bot.bot", bot_entry)
    monkeypatch.setitem(sys.modules, "bot.bot_main", bot_main)

    try:
        launcher._run_main_single_identity(bot_entry, bot_main)
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("canonical bot handoff should terminate through SystemExit")

    assert calls == ["main"]
    assert sys.modules["bot.bot"] is bot_entry


def test_launcher_source_contains_v59_runtime_proofs() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "CANONICAL_EARLY_WRITER_BOOTSTRAP_VERIFIED" in source
    assert "CANONICAL_BOT_SINGLE_IDENTITY_HANDOFF" in source
    assert 'os.environ["NIJA_CANONICAL_WRITER_FIRST_V59_READY"] = "1"' in source
    assert "local_fallback=false" in source
    assert "exact_redis_proof=true" in source
