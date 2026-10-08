"""Regression checks for operator-authorized emergency-stop latch convergence.

No order submission, risk-threshold change or forced LIVE activation.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace


def _controller(monkeypatch, tmp_path, *, local_file=False, canonical_active=False,
                durable_active=False, durable_available=True):
    monkeypatch.chdir(tmp_path)
    safety = importlib.import_module("bot.safety_controller")
    ks = importlib.import_module("bot.kill_switch")
    if local_file:
        (tmp_path / "EMERGENCY_STOP").write_text("active")
    canonical_file = tmp_path / "canonical-EMERGENCY_STOP"
    if canonical_active:
        canonical_file.write_text("active")
    canonical = SimpleNamespace(
        _kill_file=str(canonical_file),
        is_active=lambda: canonical_active,
        _read_durable_stop=lambda: (
            {"is_active": durable_active} if durable_available else None
        ),
    )
    monkeypatch.setattr(ks, "get_kill_switch", lambda: canonical)
    ctl = safety.SafetyController()
    ctl._emergency_stop_active = True
    ctl._mode = safety.TradingMode.DISABLED
    return ctl


def test_durable_cleared_stop_reconciles_latch_without_forcing_live(monkeypatch, tmp_path):
    ctl = _controller(monkeypatch, tmp_path)
    ctl.recheck_mode()
    assert ctl._emergency_stop_active is False
    assert ctl.get_current_mode().value != "live" or ctl.is_trading_allowed()[0] is True


def test_local_file_still_blocks(monkeypatch, tmp_path):
    ctl = _controller(monkeypatch, tmp_path, local_file=True)
    assert ctl.recheck_mode() is False
    assert ctl._emergency_stop_active is True


def test_canonical_stop_still_blocks(monkeypatch, tmp_path):
    ctl = _controller(monkeypatch, tmp_path, canonical_active=True)
    assert ctl.recheck_mode() is False
    assert ctl._emergency_stop_active is True


def test_durable_stop_still_blocks(monkeypatch, tmp_path):
    ctl = _controller(monkeypatch, tmp_path, durable_active=True)
    assert ctl.recheck_mode() is False
    assert ctl._emergency_stop_active is True


def test_unavailable_durable_proof_fails_closed(monkeypatch, tmp_path):
    ctl = _controller(monkeypatch, tmp_path, durable_available=False)
    assert ctl.recheck_mode() is False
    assert ctl._emergency_stop_active is True
