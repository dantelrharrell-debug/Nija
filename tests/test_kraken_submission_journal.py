from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from bot.kraken_submission_journal import (
    KrakenSubmissionJournal,
    SubmissionDenied,
    initialize_journal,
)


SCOPE = "platform:kraken"


def test_missing_journal_cannot_admit_a_submission(tmp_path: Path):
    path = tmp_path / "submission.db"
    with pytest.raises(SubmissionDenied, match="missing"):
        KrakenSubmissionJournal(path, SCOPE).reserve("first")
    assert not path.exists()


def test_restart_preserves_unknown_and_acknowledged_attempts(tmp_path: Path):
    path = tmp_path / "submission.db"
    initialize_journal(path, SCOPE)
    KrakenSubmissionJournal(path, SCOPE).reserve("first")
    restarted = KrakenSubmissionJournal(path, SCOPE)
    with pytest.raises(SubmissionDenied, match="already reserved"):
        restarted.reserve("first")
    with pytest.raises(SubmissionDenied, match="unresolved"):
        restarted.reserve("new-intent")
    restarted.record_ack("first", "exchange-id")
    restarted.record_ack("first", "exchange-id")
    with pytest.raises(SubmissionDenied, match="conflicting"):
        restarted.record_ack("first", "different-id")
    assert KrakenSubmissionJournal(path, SCOPE).unresolved_count() == 1


def test_concurrent_attempts_admit_only_one(tmp_path: Path):
    path = tmp_path / "submission.db"
    initialize_journal(path, SCOPE)

    def attempt(intent: str) -> bool:
        try:
            KrakenSubmissionJournal(path, SCOPE).reserve(intent)
        except SubmissionDenied:
            return False
        return True

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(attempt, ("same", "same", "different", "another"))) == 1


def test_invalid_storage_and_account_fail_closed(tmp_path: Path):
    path = tmp_path / "submission.db"
    path.write_bytes(b"not a database")
    with pytest.raises(SubmissionDenied, match="could not commit"):
        KrakenSubmissionJournal(path, SCOPE).reserve("first")
    other = tmp_path / "other.db"
    initialize_journal(other, "user:other:kraken")
    with pytest.raises(SubmissionDenied, match="scope mismatch"):
        KrakenSubmissionJournal(other, SCOPE).reserve("first")


def reconciliation(scope, intent_id, broker_order_id, reserved_at):
    return {
        "account_scope": scope,
        "intent_id": intent_id,
        "broker_order_id": broker_order_id,
        "observed_at": reserved_at,
        "terminal_status": "closed",
        "broker_evidence_sha256": "a" * 64,
        "ledger_evidence_sha256": "b" * 64,
    }


def test_terminal_reconciliation_releases_fence_but_retains_replay_protection(tmp_path):
    path = tmp_path / "submission.db"
    initialize_journal(path, SCOPE)
    journal = KrakenSubmissionJournal(path, SCOPE)
    journal.reserve("first")
    journal.record_ack("first", "order")
    journal.reconcile_submission("first", verify_terminal_order=reconciliation)
    restarted = KrakenSubmissionJournal(path, SCOPE)
    restarted.reconcile_submission("first", verify_terminal_order=reconciliation)
    assert restarted.unresolved_count() == 0
    with pytest.raises(SubmissionDenied, match="already reserved"):
        restarted.reserve("first")
    restarted.reserve("next")


@pytest.mark.parametrize("change", [
    {"broker_order_id": "different"},
    {"terminal_status": "open"},
    {"ledger_evidence_sha256": None},
    {"observed_at": 0},
    {"account_scope": "user:other:kraken"},
])
def test_invalid_reconciliation_preserves_fence(tmp_path, change):
    path = tmp_path / "submission.db"
    initialize_journal(path, SCOPE)
    journal = KrakenSubmissionJournal(path, SCOPE)
    with pytest.raises(SubmissionDenied, match="reservation missing"):
        journal.reconcile_submission("first", verify_terminal_order=reconciliation)
    journal.reserve("first")
    journal.record_ack("first", "order")
    with pytest.raises(SubmissionDenied, match="invalid"):
        journal.reconcile_submission(
            "first", verify_terminal_order=lambda *args: {**reconciliation(*args), **change}
        )
    assert journal.unresolved_count() == 1


def test_sqlite_backup_restore_preserves_resolved_and_ambiguous_intents(tmp_path):
    original = tmp_path / "original.db"
    restored = tmp_path / "restored.db"
    initialize_journal(original, SCOPE)
    journal = KrakenSubmissionJournal(original, SCOPE)
    journal.reserve("resolved")
    journal.record_ack("resolved", "order")
    journal.reconcile_submission("resolved", verify_terminal_order=reconciliation)
    journal.reserve("ambiguous")

    with closing(sqlite3.connect(original)) as source, closing(sqlite3.connect(restored)) as target:
        source.backup(target)
        assert target.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    reopened = KrakenSubmissionJournal(restored, SCOPE)
    assert reopened.unresolved_count() == 1
    with pytest.raises(SubmissionDenied, match="already reserved"):
        reopened.reserve("resolved")
    with pytest.raises(SubmissionDenied, match="already reserved"):
        reopened.reserve("ambiguous")
    with pytest.raises(SubmissionDenied, match="unresolved"):
        reopened.reserve("new")
