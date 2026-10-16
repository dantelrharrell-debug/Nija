"""v459: no future-dated or nonfinite capital/heartbeat proof is fresh."""
import pytest

import preactivation_readiness_convergence_v16_patch as v16


def _capital(monkeypatch, accepted_at):
    monkeypatch.setenv("NIJA_CAPITAL_READINESS_HANDOFF_V34", "true")
    monkeypatch.setenv("NIJA_CAPITAL_HANDOFF_ACCEPTED_TS", str(accepted_at))
    monkeypatch.setenv("NIJA_CAPITAL_HANDOFF_REAL", "100")
    monkeypatch.setenv("NIJA_CAPITAL_HANDOFF_BROKER_COUNT", "1")
    monkeypatch.setenv("NIJA_CAPITAL_HANDOFF_TTL_S", "90")


def test_future_capital_handoff_is_not_accepted(monkeypatch):
    monkeypatch.setattr(v16.time, "time", lambda: 1000.0)
    _capital(monkeypatch, 1006.0)
    assert v16._fresh_capital_handoff() is None


def test_small_capital_clock_skew_is_tolerated(monkeypatch):
    monkeypatch.setattr(v16.time, "time", lambda: 1000.0)
    _capital(monkeypatch, 1002.0)
    record = v16._fresh_capital_handoff()
    assert record is not None and record["hydrated"] is True
    assert record["handoff_age_s"] == 0


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "1e9999"])
def test_invalid_capital_numbers_fail_closed(monkeypatch, bad):
    monkeypatch.setattr(v16.time, "time", lambda: 1000.0)
    _capital(monkeypatch, 999.0)
    monkeypatch.setenv("NIJA_CAPITAL_HANDOFF_REAL", bad)
    assert v16._fresh_capital_handoff() is None


def test_writer_heartbeat_rejects_future_timestamp(monkeypatch):
    monkeypatch.setattr(v16.time, "time", lambda: 1000.0)
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "1040")
    ok, detail = v16._heartbeat_ready()
    assert ok is False
    assert "future" in detail


def test_writer_heartbeat_works_when_fresh(monkeypatch):
    monkeypatch.setattr(v16.time, "time", lambda: 1000.0)
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "999")
    ok, detail = v16._heartbeat_ready()
    assert ok is True
    assert "fresh" in detail


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "1e9999"])
def test_writer_heartbeat_rejects_invalid_time(monkeypatch, bad):
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", bad)
    assert v16._heartbeat_ready()[0] is False


def test_float_rejects_nonfinite_values():
    assert v16._float("nan", 42.0) == 42.0
    assert v16._float("inf", 42.0) == 42.0
    assert v16._float("1e9999", 42.0) == 42.0


def test_stale_capital_handoff_is_rejected(monkeypatch):
    monkeypatch.setattr(v16.time, "time", lambda: 1000.0)
    _capital(monkeypatch, 900.0)
    assert v16._fresh_capital_handoff() is None


def test_writer_heartbeat_tolerates_small_clock_skew(monkeypatch):
    monkeypatch.setattr(v16.time, "time", lambda: 1000.0)
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "1002")
    assert v16._heartbeat_ready()[0] is True


def test_stale_writer_heartbeat_is_rejected(monkeypatch):
    monkeypatch.setattr(v16.time, "time", lambda: 1000.0)
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "850")
    assert v16._heartbeat_ready()[0] is False
