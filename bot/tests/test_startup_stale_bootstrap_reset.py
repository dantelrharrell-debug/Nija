"""Regression coverage for stale BootstrapFSM fresh-start normalization."""

from __future__ import annotations

from pathlib import Path


def _bot_source() -> str:
    return (Path(__file__).resolve().parents[2] / "bot.py").read_text(encoding="utf-8")


def test_fresh_attempt_resets_stale_advanced_bootstrap_state_before_logging_phase():
    source = _bot_source()
    assert "def _reset_stale_bootstrap_fsm_for_fresh_attempt" in source
    assert "_BootstrapState.CAPITAL_READY" in source
    assert "_BootstrapState.RUNNING_SUPERVISED" in source
    assert "resetting to BOOT_FAILED_RETRY before strict bootstrap" in source

    reset_call = source.index("_reset_stale_bootstrap_fsm_for_fresh_attempt(init_done=_pre_init_done)")
    attempt_log = source.index('"🔁 [Startup] Bootstrap attempt #%d (%s, %s)"')
    assert reset_call < attempt_log
