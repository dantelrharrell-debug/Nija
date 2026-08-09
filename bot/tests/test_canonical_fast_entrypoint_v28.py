from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
from types import ModuleType
import threading


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "canonical_runtime_launcher_v26.py"
BOT_ENTRYPOINT = ROOT / "bot" / "bot.py"
ATTESTATION = ROOT / "scripts" / "runtime_entrypoint_attestation.py"
V51 = ROOT / "bot" / "zero_signal_streak_cap_repair_v51_patch.py"
V52 = ROOT / "bot" / "writer_distributed_loss_watchdog_v52_patch.py"
V53 = ROOT / "bot" / "writer_release_state_consistency_v53_patch.py"
V54 = ROOT / "bot" / "writer_runtime_lifecycle_supervisor_v54_patch.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_launcher_preserves_defer_flag_through_main_handoff(monkeypatch, tmp_path) -> None:
    launcher = _load("test_canonical_fast_entrypoint_v28", LAUNCHER)
    fake_main = tmp_path / "main.py"
    fake_main.write_text("pass\n", encoding="utf-8")
    observed: dict[str, str] = {}
    bot_entry = ModuleType("bot.bot")
    bot_main = ModuleType("bot.bot_main")

    monkeypatch.delenv("NIJA_DEFER_RUNTIME_SITE_HOOKS", raising=False)
    monkeypatch.delenv("NIJA_CANONICAL_ENTRYPOINT_FAST_PATH", raising=False)
    monkeypatch.setattr(launcher, "MAIN_PATH", fake_main)
    monkeypatch.setattr(launcher, "install_canonical_startup_guard", lambda: object())
    monkeypatch.setattr(
        launcher,
        "_bootstrap_writer_first",
        lambda: (bot_entry, bot_main),
    )

    def _run_path(path: str, *, run_name: str) -> None:
        observed["path"] = path
        observed["run_name"] = run_name
        observed["defer"] = os.environ.get("NIJA_DEFER_RUNTIME_SITE_HOOKS", "")
        observed["fast"] = os.environ.get("NIJA_CANONICAL_ENTRYPOINT_FAST_PATH", "")

    monkeypatch.setattr(launcher.runpy, "run_path", _run_path)
    monkeypatch.setattr(
        launcher,
        "_run_main_single_identity",
        lambda entry, main: launcher.runpy.run_path(str(launcher.MAIN_PATH), run_name="__main__"),
    )

    assert launcher.main() == 0
    assert observed == {
        "path": str(fake_main),
        "run_name": "__main__",
        "defer": "1",
        "fast": "1",
    }


def test_bot_entrypoint_fast_path_is_small_and_fail_closed() -> None:
    source = BOT_ENTRYPOINT.read_text(encoding="utf-8")

    assert "CANONICAL_ENTRYPOINT_FAST_PATH_READY" in source
    assert "package_hook_fanout=deferred" in source
    assert 'os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"' in source
    assert 'os.environ["NIJA_RUNTIME_TRADING_STATE"] = "OFF"' in source

    fast_block = source.split("_FAST_PATH_INSTALLERS = (", 1)[1].split(
        ")\n\n_LEGACY_INSTALLERS", 1
    )[0]
    assert "writer_reelection_loss_reason_v46_patch" in fast_block
    assert "WRITER_REELECTION_LOSS_REASON_V46" in fast_block
    assert "writer_generation_state_gate_v50_patch" in fast_block
    assert "WRITER_GENERATION_STATE_GATE_V50" in fast_block
    assert "writer_distributed_loss_watchdog_v52_patch" in fast_block
    assert "WRITER_DISTRIBUTED_LOSS_WATCHDOG_V52" in fast_block
    assert "writer_release_state_consistency_v53_patch" in fast_block
    assert "WRITER_RELEASE_STATE_V53" in fast_block
    assert "writer_runtime_lifecycle_supervisor_v54_patch" in fast_block
    assert "WRITER_RUNTIME_LIFECYCLE_V54" in fast_block
    assert "zero_signal_streak_cap_repair_v51_patch" in fast_block
    assert "ZERO_SIGNAL_STREAK_CAP_V51" in fast_block
    assert "okx_final_order_submission_bridge_patch" in fast_block
    assert "startup_authority_prereq_repair_patch" in fast_block
    assert "stalled_writer_release_guard_v22" in fast_block
    assert "trading_engine_strategy_wrapper_patch" not in fast_block
    assert "canonical_broker_main_entry_guard_v20" not in fast_block


def test_v51_restores_missing_cap_guard_without_removing_state_repair(monkeypatch) -> None:
    v51 = _load("test_zero_signal_streak_cap_v51_fast_path", V51)
    core = ModuleType("bot.nija_core_loop")

    def leaf(self, broker, snapshot, symbols, slots, streak=0):
        return streak

    def state_repair(self, broker, snapshot, symbols, slots, streak=0):
        return leaf(self, broker, snapshot, symbols, slots, streak)

    state_repair.__wrapped__ = leaf
    setattr(state_repair, v51._STATE_ATTR, True)
    core.NijaCoreLoop = type("NijaCoreLoop", (), {"_phase3_scan_and_enter": state_repair})
    monkeypatch.setitem(sys.modules, "bot.nija_core_loop", core)
    monkeypatch.delitem(sys.modules, "nija_core_loop", raising=False)
    monkeypatch.setenv("NIJA_ZERO_SIGNAL_STREAK_CAP", "12")

    assert v51._install_on_core_loop(core) is True
    current = core.NijaCoreLoop._phase3_scan_and_enter
    cap_found, cap_cycle, _ = v51._chain_contains(current)
    state_found, state_cycle, _ = v51._chain_contains(current, v51._STATE_ATTR)

    assert cap_found is True
    assert state_found is True
    assert cap_cycle is False
    assert state_cycle is False
    assert current(object(), None, None, None, None, 99) == 12


def test_v52_missing_distributed_lock_marks_existing_runtime_lost(monkeypatch) -> None:
    v52 = _load("test_writer_distributed_loss_v52_fast_path", V52)

    class Client:
        def get(self, _key):
            return None

    class Runtime:
        acquired = True
        lost = False
        _local_fallback = False
        _client = Client()
        _lock_key = "nija:writer_lock:process"
        _lock_value = "2044:owner"
        _token = "2044"
        _generation = 18

        def __init__(self):
            self.marked = []

        def _mark_lost(self, reason):
            self.marked.append(reason)
            self.lost = True

    runtime = Runtime()
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_EXECUTION_ACTIVE", "true")

    result = v52.reconcile_once(runtime)

    assert result["state"] == "missing"
    assert result["action"] == "mark_lost_recoverable"
    assert runtime.marked == ["lock_missing_and_fencing_token_mismatch"]
    assert runtime.lost is True
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_EXECUTION_ACTIVE"] == "false"


def test_v53_release_invalidates_stale_local_acquisition_without_callback(monkeypatch) -> None:
    v53 = _load("test_writer_release_state_v53_fast_path", V53)
    calls = []

    class Runtime:
        def __init__(self):
            self._lost = threading.Event()
            self._result = type("Result", (), {"acquired": True})()
            self._on_lost_callback = lambda reason: calls.append(reason)

        @property
        def acquired(self):
            return bool(self._result and self._result.acquired and not self._lost.is_set())

        @property
        def lost(self):
            return self._lost.is_set()

        def release(self):
            return True

    module = ModuleType("bot.entrypoint_writer_authority")
    module.EntrypointWriterAuthority = Runtime
    assert v53._patch_entrypoint_writer_authority(module) is True

    runtime = Runtime()
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_EXECUTION_ACTIVE", "true")

    assert runtime.acquired is True
    assert runtime.release() is True
    assert runtime.acquired is False
    assert runtime.lost is True
    assert calls == []
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_EXECUTION_ACTIVE"] == "false"


def test_v54_blocks_core_start_without_exact_writer_proof(monkeypatch) -> None:
    v54 = _load("test_writer_runtime_v54_fast_path", V54)
    core = ModuleType("bot.nija_core_loop")
    called = []

    def start_trading_engine(strategy):
        called.append(strategy)
        return object()

    core.start_trading_engine = start_trading_engine
    monkeypatch.setattr(v54, "_writer_proof", lambda: (False, "writer_lease_not_acquired", 0))
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_EXECUTION_ACTIVE", "true")

    assert v54._patch_core_loop(core) is True
    try:
        core.start_trading_engine(object())
        assert False, "core start should be blocked"
    except RuntimeError as exc:
        assert "writer_runtime_v54_core_start_blocked" in str(exc)

    assert called == []
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_EXECUTION_ACTIVE"] == "false"


def test_v54_requests_normal_shutdown_when_live_core_loses_writer(monkeypatch) -> None:
    v54 = _load("test_writer_runtime_v54_shutdown", V54)
    shutdown = threading.Event()
    bot_main = ModuleType("bot.bot_main")
    bot_main._shutdown_event = shutdown
    bot_main._core_loop_thread = type("Thread", (), {"is_alive": lambda self: True})()
    monkeypatch.setitem(sys.modules, "bot.bot_main", bot_main)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_EXECUTION_ACTIVE", "true")

    assert v54._request_canonical_shutdown("writer_lease_not_acquired") is True
    assert shutdown.is_set() is True
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_EXECUTION_ACTIVE"] == "false"


def test_runtime_attestation_requires_fast_path_and_strategy_handoff() -> None:
    source = ATTESTATION.read_text(encoding="utf-8")

    assert "CANONICAL_ENTRYPOINT_FAST_PATH_ARMED" in source
    assert "CANONICAL_ENTRYPOINT_FAST_PATH_READY" in source
    assert "_publish_canonical_strategy_for_runtime" in source
    assert "CANONICAL_STRATEGY_HANDOFF_READY" in source
