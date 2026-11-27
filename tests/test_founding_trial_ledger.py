"""Synthetic ledger tests; no broker, Stripe or production credentials."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from founding_trial_ledger import ExecutionOwnershipConflict, FoundingTrialLedger


@pytest.mark.parametrize("operation", ["record_fill", "cancel"])
def test_failed_write_lock_preserves_original_error(tmp_path, monkeypatch, operation):
    path = tmp_path / "trial.db"
    ledger = FoundingTrialLedger(path)
    connect = ledger._connect

    def without_wait():
        conn = connect()
        conn.execute("PRAGMA busy_timeout=0")
        return conn

    monkeypatch.setattr(ledger, "_connect", without_wait)
    arguments = ("member",)
    if operation == "record_fill":
        arguments += ("execution", datetime.now(timezone.utc))
    with closing(sqlite3.connect(path)) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            getattr(ledger, operation)(*arguments)
    assert ledger.get("member") is None

T0 = datetime(2026, 11, 23, 16, 0, tzinfo=timezone.utc)


@pytest.fixture
def ledger(tmp_path):
    return FoundingTrialLedger(tmp_path / 'first_fill.db')


def test_first_fill_starts_exact_14_day_window(ledger):
    record = ledger.record_fill('user1', 'broker:trade:100', T0)
    assert record.state == 'trialing'
    assert record.starts_at == '2026-11-23T16:00:00+00:00'
    assert record.ends_at == '2026-12-07T16:00:00+00:00'
    assert ledger.get('user1') == record


def test_replay_and_later_fill_do_not_restart_trial(ledger):
    first = ledger.record_fill('user1', 'broker:trade:100', T0)
    assert ledger.record_fill('user1', 'broker:trade:100', T0) == first
    assert ledger.record_fill('user1', 'broker:trade:101', T0 + timedelta(days=1)) == first
    assert ledger.record_fill('user1', 'broker:trade:099', T0 - timedelta(days=1)) == first


def test_cross_member_execution_replay_is_rejected(ledger):
    ledger.record_fill('user1', 'broker:trade:100', T0)
    with pytest.raises(ExecutionOwnershipConflict):
        ledger.record_fill('user2', 'broker:trade:100', T0)
    assert ledger.get('user2') is None


def test_cancel_before_fill_prevents_subsequent_activation(ledger):
    canceled = ledger.cancel('user1')
    assert canceled.state == 'canceled' and canceled.execution_id is None
    assert ledger.record_fill('user1', 'broker:trade:100', T0) == canceled
    assert ledger.cancel('user1') == canceled


def test_cancel_after_fill_remains_terminal(ledger):
    ledger.record_fill('user1', 'broker:trade:100', T0)
    canceled = ledger.cancel('user1')
    assert canceled.state == 'canceled'
    assert canceled.starts_at == '2026-11-23T16:00:00+00:00'
    assert ledger.record_fill('user1', 'broker:trade:101', T0 + timedelta(days=2)) == canceled


def test_persists_across_process_style_reopen(tmp_path):
    db_path = tmp_path / 'trial.db'
    FoundingTrialLedger(db_path).record_fill('user1', 'broker:trade:100', T0)
    assert FoundingTrialLedger(db_path).get('user1').execution_id == 'broker:trade:100'


def test_concurrent_identical_fill_is_idempotent(ledger):
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(lambda _: ledger.record_fill('user1', 'broker:trade:100', T0), range(12)))
    assert len(set(records)) == 1


def test_invalid_inputs_fail_before_database_mutation(ledger):
    with pytest.raises(ValueError):
        ledger.record_fill('user1', 'broker:trade:100', datetime(2026, 11, 23, 16))
    with pytest.raises(ValueError):
        ledger.record_fill(' user1', 'broker:trade:100', T0)
    with pytest.raises(ValueError):
        ledger.record_fill('user1', '', T0)
    assert ledger.get('user1') is None


def test_memory_db_not_allowed():
    with pytest.raises(ValueError):
        FoundingTrialLedger(':memory:')
