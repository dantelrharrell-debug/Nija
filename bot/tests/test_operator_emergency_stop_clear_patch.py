from __future__ import annotations

import json

from bot import operator_emergency_stop_clear_patch as patch


def _operator_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_OPERATOR_CLEAR_EMERGENCY_STOP", "true")
    monkeypatch.setenv("NIJA_OPERATOR_CLEAR_EMERGENCY_STOP_ACK", "CLEAR_EMERGENCY_STOP_FOR_LIVE_TRADING")
    monkeypatch.setenv("NIJA_OPERATOR_CLEAR_EMERGENCY_STOP_REASON", "Operator reviewed current logs and approves clearing manual emergency stop.")
    monkeypatch.setenv("NIJA_EMERGENCY_STOP_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    monkeypatch.setenv("NIJA_AUTO_CLEAR_STALE_MANUAL_EMERGENCY_ENV", "true")
    for name in (
        "NIJA_FORCE_ACTIVATION",
        "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK",
        "NIJA_DISABLE_WRITER_LOCK",
        "NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK",
        "NIJA_CLEAR_TERMINAL_RISK_BLOCKS",
        "NIJA_BYPASS_RISK_GATES",
    ):
        monkeypatch.delenv(name, raising=False)


def test_operator_clear_quarantines_kill_and_state_files(monkeypatch, tmp_path):
    kill_file = tmp_path / "EMERGENCY_STOP"
    state_file = tmp_path / ".nija_kill_switch_state.json"
    kill_file.write_text("manual emergency stop active\n", encoding="utf-8")
    state_file.write_text(json.dumps({"reason": "manual operator stop", "source": "operator"}), encoding="utf-8")
    _operator_env(monkeypatch, tmp_path)
    monkeypatch.setenv("NIJA_EMERGENCY_STOP_FILES", str(kill_file))
    monkeypatch.setenv("NIJA_EMERGENCY_STOP_STATE_FILES", str(state_file))
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "EMERGENCY_STOP")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")

    cleared = patch.run_once()

    assert cleared == 2
    assert not kill_file.exists()
    assert not state_file.exists()
    assert (tmp_path / "quarantine").exists()
    assert patch.os.environ["NIJA_RUNTIME_TRADING_STATE"] == "OFF"
    assert patch.os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"


def test_operator_clear_refuses_terminal_risk_reason(monkeypatch, tmp_path):
    kill_file = tmp_path / "EMERGENCY_STOP"
    kill_file.write_text("daily loss limit reached\n", encoding="utf-8")
    _operator_env(monkeypatch, tmp_path)
    monkeypatch.setenv("NIJA_EMERGENCY_STOP_FILES", str(kill_file))
    monkeypatch.setenv("NIJA_EMERGENCY_STOP_STATE_FILES", "")

    cleared = patch.run_once()

    assert cleared == 0
    assert kill_file.exists()


def test_operator_clear_requires_exact_ack(monkeypatch, tmp_path):
    kill_file = tmp_path / "EMERGENCY_STOP"
    kill_file.write_text("manual emergency stop active\n", encoding="utf-8")
    _operator_env(monkeypatch, tmp_path)
    monkeypatch.setenv("NIJA_OPERATOR_CLEAR_EMERGENCY_STOP_ACK", "clear it")
    monkeypatch.setenv("NIJA_EMERGENCY_STOP_FILES", str(kill_file))
    monkeypatch.setenv("NIJA_EMERGENCY_STOP_STATE_FILES", "")

    cleared = patch.run_once()

    assert cleared == 0
    assert kill_file.exists()


def test_stale_manual_env_only_stop_clears_without_files(monkeypatch, tmp_path):
    _operator_env(monkeypatch, tmp_path)
    monkeypatch.setenv("NIJA_EMERGENCY_STOP_FILES", str(tmp_path / "missing_EMERGENCY_STOP"))
    monkeypatch.setenv("NIJA_EMERGENCY_STOP_STATE_FILES", str(tmp_path / "missing_state.json"))
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "EMERGENCY_STOP")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setenv("NIJA_EMERGENCY_STOP_REASON", "manual emergency stop active from removed file")

    cleared = patch.run_once()

    assert cleared == 1
    assert patch.os.environ["NIJA_RUNTIME_TRADING_STATE"] == "OFF"
    assert patch.os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert "NIJA_EMERGENCY_STOP_REASON" not in patch.os.environ


def test_stale_env_only_clear_refuses_terminal_risk(monkeypatch, tmp_path):
    _operator_env(monkeypatch, tmp_path)
    monkeypatch.setenv("NIJA_EMERGENCY_STOP_FILES", str(tmp_path / "missing_EMERGENCY_STOP"))
    monkeypatch.setenv("NIJA_EMERGENCY_STOP_STATE_FILES", str(tmp_path / "missing_state.json"))
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "EMERGENCY_STOP")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setenv("NIJA_EMERGENCY_STOP_REASON", "daily loss limit reached")

    cleared = patch.run_once()

    assert cleared == 0
    assert patch.os.environ["NIJA_RUNTIME_TRADING_STATE"] == "EMERGENCY_STOP"
    assert patch.os.environ["NIJA_EMERGENCY_STOP_REASON"] == "daily loss limit reached"
