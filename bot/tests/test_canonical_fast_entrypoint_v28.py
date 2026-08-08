from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "canonical_runtime_launcher_v26.py"
BOT_ENTRYPOINT = ROOT / "bot" / "bot.py"
ATTESTATION = ROOT / "scripts" / "runtime_entrypoint_attestation.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_launcher_preserves_defer_flag_through_main_handoff(
    monkeypatch, tmp_path
) -> None:
    launcher = _load("test_canonical_fast_entrypoint_v28", LAUNCHER)
    fake_main = tmp_path / "main.py"
    fake_main.write_text("pass\n", encoding="utf-8")
    observed: dict[str, str] = {}

    monkeypatch.delenv("NIJA_DEFER_RUNTIME_SITE_HOOKS", raising=False)
    monkeypatch.delenv("NIJA_CANONICAL_ENTRYPOINT_FAST_PATH", raising=False)
    monkeypatch.setattr(launcher, "MAIN_PATH", fake_main)
    monkeypatch.setattr(launcher, "install_canonical_startup_guard", lambda: object())

    def _run_path(path: str, *, run_name: str) -> None:
        observed["path"] = path
        observed["run_name"] = run_name
        observed["defer"] = os.environ.get("NIJA_DEFER_RUNTIME_SITE_HOOKS", "")
        observed["fast"] = os.environ.get("NIJA_CANONICAL_ENTRYPOINT_FAST_PATH", "")

    monkeypatch.setattr(launcher.runpy, "run_path", _run_path)

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
    assert "zero_signal_streak_cap_repair_v51_patch" in fast_block
    assert "ZERO_SIGNAL_STREAK_CAP_V51" in fast_block
    assert "okx_final_order_submission_bridge_patch" in fast_block
    assert "startup_authority_prereq_repair_patch" in fast_block
    assert "stalled_writer_release_guard_v22" in fast_block
    assert "trading_engine_strategy_wrapper_patch" not in fast_block
    assert "canonical_broker_main_entry_guard_v20" not in fast_block


def test_runtime_attestation_requires_fast_path_and_strategy_handoff() -> None:
    source = ATTESTATION.read_text(encoding="utf-8")

    assert "CANONICAL_ENTRYPOINT_FAST_PATH_ARMED" in source
    assert "CANONICAL_ENTRYPOINT_FAST_PATH_READY" in source
    assert "_publish_canonical_strategy_for_runtime" in source
    assert "CANONICAL_STRATEGY_HANDOFF_READY" in source
