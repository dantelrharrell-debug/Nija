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


def test_orphaned_terminal_record_cannot_pre_resolve_a_new_reservation(tmp_path: Path):
    path = tmp_path / "submission.db"
    initialize_journal(path, SCOPE)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute(
            "INSERT INTO submission_resolution VALUES (?, ?, ?, ?, ?)",
            ("orphaned-intent", 1.0, "closed", "a" * 64, "b" * 64),
        )

    journal = KrakenSubmissionJournal(path, SCOPE)
    with pytest.raises(SubmissionDenied, match="terminal evidence without a reservation"):
        journal.reserve("orphaned-intent")
    with pytest.raises(SubmissionDenied, match="terminal evidence without a reservation"):
        journal.reserve("different-intent")
    with pytest.raises(SubmissionDenied, match="terminal evidence without a reservation"):
        journal.unresolved_count()

    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT count(*) FROM submission").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM submission_resolution").fetchone() == (1,)


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


@pytest.mark.parametrize("stored_order_id", [None, "", "   "])
def test_restored_terminal_record_requires_stored_order_reference(tmp_path, stored_order_id):
    path = tmp_path / "submission.db"
    initialize_journal(path, SCOPE)
    journal = KrakenSubmissionJournal(path, SCOPE)
    journal.reserve("existing")
    journal.record_ack("existing", "order")
    journal.reconcile_submission("existing", verify_terminal_order=reconciliation)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE submission SET broker_order_id=?", (stored_order_id,))

    restarted = KrakenSubmissionJournal(path, SCOPE)
    with pytest.raises(SubmissionDenied, match="terminal evidence without a broker order reference"):
        restarted.unresolved_count()
    with pytest.raises(SubmissionDenied, match="terminal evidence without a broker order reference"):
        restarted.reserve("next")

    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT intent_id, broker_order_id FROM submission").fetchall() == [
            ("existing", stored_order_id)
        ]
        assert db.execute("SELECT intent_id FROM submission_resolution").fetchall() == [("existing",)]


@pytest.mark.parametrize("change", [
    {"terminal_status": "open"},
    {"observed_at": 0},
    {"observed_at": 1e20},
    {"observed_at": "unknown"},
    {"broker_evidence_sha256": "g" * 64},
    {"ledger_evidence_sha256": "b" * 64 + "\x00invalid"},
])
def test_restored_terminal_record_requires_valid_evidence_metadata(tmp_path, change):
    path = tmp_path / "submission.db"
    initialize_journal(path, SCOPE)
    journal = KrakenSubmissionJournal(path, SCOPE)
    journal.reserve("existing")
    journal.record_ack("existing", "order")
    with closing(sqlite3.connect(path)) as db, db:
        reserved_at = db.execute("SELECT reserved_at FROM submission").fetchone()[0]
        evidence = {**reconciliation(SCOPE, "existing", "order", reserved_at), **change}
        db.execute(
            """INSERT INTO submission_resolution VALUES (
                   :intent_id, :observed_at, :terminal_status, :broker_evidence_sha256, :ledger_evidence_sha256
               )""",
            evidence,
        )

    restarted = KrakenSubmissionJournal(path, SCOPE)
    with pytest.raises(SubmissionDenied, match="invalid terminal evidence metadata"):
        restarted.unresolved_count()
    with pytest.raises(SubmissionDenied, match="invalid terminal evidence metadata"):
        restarted.reserve("next")
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT intent_id FROM submission").fetchall() == [("existing",)]
        assert db.execute("SELECT intent_id FROM submission_resolution").fetchall() == [("existing",)]


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


def test_interrupted_install_allows_clean_retry(tmp_path, monkeypatch):
    path = tmp_path / "journal.db"

    def fail_connect(*args, **kwargs):
        raise sqlite3.OperationalError("installation interrupted")

    with monkeypatch.context() as failure:
        failure.setattr(sqlite3, "connect", fail_connect)
        with pytest.raises(sqlite3.OperationalError):
            initialize_journal(path, SCOPE)
    assert not path.exists()
    initialize_journal(path, SCOPE)
    assert KrakenSubmissionJournal(path, SCOPE).unresolved_count() == 0
    assert path.stat().st_mode & 0o777 == 0o600


def test_concurrent_install_preserves_winner_and_pending_intent(tmp_path):
    path = tmp_path / "journal.db"

    def install(scope):
        try:
            initialize_journal(path, scope)
        except FileExistsError:
            return None
        return scope

    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = [s for s in pool.map(install, (SCOPE, "user:other:kraken")) if s]
    assert len(winners) == 1
    journal = KrakenSubmissionJournal(path, winners[0])
    journal.reserve("pending")
    with pytest.raises(FileExistsError):
        initialize_journal(path, SCOPE)
    assert journal.unresolved_count() == 1


def test_live_add_order_requires_configured_journal(monkeypatch):
    from bot.kraken_submission_journal import query_direct_order

    monkeypatch.delenv("NIJA_KRAKEN_SUBMISSION_JOURNAL_PATH", raising=False)

    class NoTransport:
        def query_private(self, method, params):
            raise AssertionError("unprotected live order reached Kraken transport")

    class Broker:
        api = NoTransport()

    with pytest.raises(SubmissionDenied, match="not configured"):
        query_direct_order(Broker(), "AddOrder", {"pair": "XBTUSD"}, assert_deadline=lambda method: None)


@pytest.mark.parametrize("journal_configured", [False, True])
@pytest.mark.parametrize("validate_only", [False, True])
def test_batch_order_rejected_without_transport(
    monkeypatch, tmp_path, journal_configured, validate_only,
):
    """Deny batch submissions before transport with or without a journal."""
    from bot.kraken_submission_journal import query_direct_order

    if journal_configured:
        monkeypatch.setenv(
            "NIJA_KRAKEN_SUBMISSION_JOURNAL_PATH", str(tmp_path / "journal.db")
        )
    else:
        monkeypatch.delenv("NIJA_KRAKEN_SUBMISSION_JOURNAL_PATH", raising=False)

    calls = []

    class NoTransport:
        def query_private(self, method, params):
            calls.append((method, dict(params)))
            raise AssertionError("unsupported AddOrderBatch reached Kraken transport")

    class Broker:
        api = NoTransport()

    params = {
        "orders": [] if validate_only else [{"pair": "XBTUSD"}],
        "validate": validate_only,
    }
    with pytest.raises(SubmissionDenied, match="batch Kraken order submission"):
        query_direct_order(
            Broker(), "AddOrderBatch", params, assert_deadline=lambda method: None,
        )
    assert calls == []


def test_validate_only_add_order_still_allowed_without_journal(monkeypatch):
    """Preserve the single-order validation behavior; never execute a trade."""
    from bot.kraken_submission_journal import query_direct_order

    monkeypatch.delenv("NIJA_KRAKEN_SUBMISSION_JOURNAL_PATH", raising=False)
    calls = []

    class Transport:
        def query_private(self, method, params):
            calls.append((method, dict(params)))
            return {"error": [], "result": {"descr": {}}}

    class Broker:
        api = Transport()

    params = {"pair": "XBTUSD", "validate": True}
    result = query_direct_order(
        Broker(), "AddOrder", params, assert_deadline=lambda method: None,
    )
    assert result["error"] == []
    assert calls == [("AddOrder", params)]
