"""Regression tests for NIJA's canonical live authorization gate.

These tests lock the safety invariant that LIVE_TRADING is requested intent
only; it must not authorize real-money execution without
LIVE_CAPITAL_VERIFIED.
"""

from bot.runtime_mode import resolve_runtime_mode


def _clear_modes(monkeypatch):
    for name in (
        "DRY_RUN_MODE",
        "PAPER_MODE",
        "LIVE_CAPITAL_VERIFIED",
        "LIVE_TRADING",
    ):
        monkeypatch.delenv(name, raising=False)


def test_live_trading_alias_alone_is_monitor_only(monkeypatch):
    _clear_modes(monkeypatch)
    monkeypatch.setenv("LIVE_TRADING", "true")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "false")

    mode = resolve_runtime_mode()

    assert mode.live_trading is True
    assert mode.live_capital_verified is False
    assert mode.live_authorized is False
    assert mode.is_live is False
    assert mode.mode == "monitor"
    assert mode.source == "LIVE_TRADING_REQUESTED_NOT_AUTHORIZED"
    assert "live_trading_without_capital_verification" in mode.conflicts


def test_canonical_live_capital_verification_authorizes_live(monkeypatch):
    _clear_modes(monkeypatch)
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")

    mode = resolve_runtime_mode()

    assert mode.live_authorized is True
    assert mode.is_live is True
    assert mode.mode == "live"
    assert mode.source == "LIVE_CAPITAL_VERIFIED"


def test_paper_mode_overrides_live_authorization(monkeypatch):
    _clear_modes(monkeypatch)
    monkeypatch.setenv("PAPER_MODE", "true")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")

    mode = resolve_runtime_mode()

    assert mode.live_authorized is True
    assert mode.is_live is False
    assert mode.mode == "paper"
    assert mode.source == "PAPER_MODE"
    assert "paper_vs_live" in mode.conflicts


def test_dry_run_mode_overrides_live_authorization(monkeypatch):
    _clear_modes(monkeypatch)
    monkeypatch.setenv("DRY_RUN_MODE", "true")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")

    mode = resolve_runtime_mode()

    assert mode.live_authorized is True
    assert mode.is_live is False
    assert mode.mode == "dry_run"
    assert mode.source == "DRY_RUN_MODE"
    assert "dry_run_vs_live" in mode.conflicts
