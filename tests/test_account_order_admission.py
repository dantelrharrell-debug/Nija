"""Offline reservation tests. Synthetic collectors are not production proof."""
from dataclasses import replace
import importlib.util
import multiprocessing
from pathlib import Path
import sqlite3
import sys
import time
import types
import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'offline_account_admission'
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT / 'bot')]
sys.modules[PACKAGE] = pkg
for name in ('order_admission_policy', 'account_order_admission'):
    spec = importlib.util.spec_from_file_location(PACKAGE + '.' + name, ROOT / 'bot' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
policy = sys.modules[PACKAGE + '.order_admission_policy']
api = sys.modules[PACKAGE + '.account_order_admission']
C = policy.Candidate('kraken:synthetic-account', 'synthetic-credential', 3, 'a' * 64)


def collector(candidate, conn):
    conn.execute('SELECT COUNT(*) FROM trade_ledger').fetchone()
    return ({name: policy.CurrentFact(candidate, True, time.time(), 'offline-test-only')
             for name in policy.REQUIRED_CONTROLS}, policy.OrderOutcome(candidate.account, 'none'))


def fence(candidate):
    pass


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / 'ledger.db'
    with sqlite3.connect(path) as conn:
        for table in ('trade_ledger', 'open_positions', 'completed_trades', 'strategy_order_intents'):
            conn.execute('CREATE TABLE ' + table + ' (id INTEGER)')
    api.AccountOrderAdmission(path, collector, fence).install_schema()
    return path


def worker(path, index, barrier, queue):
    store = api.AccountOrderAdmission(Path(path), collector, fence)
    barrier.wait()
    try:
        store.reserve(replace(C, intent_digest=f'{index:064x}'))
        queue.put('reserved')
    except api.AdmissionDenied:
        queue.put('denied')


def test_processes_different_ids_same_account_only_one_wins(ledger):
    ctx = multiprocessing.get_context('spawn')
    barrier, queue = ctx.Barrier(6), ctx.Queue()
    processes = [ctx.Process(target=worker, args=(str(ledger), i, barrier, queue)) for i in range(6)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0
    outcomes = [queue.get(timeout=1) for _ in processes]
    assert outcomes.count('reserved') == 1
    assert outcomes.count('denied') == 5


def test_restart_timeout_and_rotated_key_do_not_release_account(ledger):
    first = api.AccountOrderAdmission(ledger, collector, fence)
    reservation = first.reserve(C)
    first.consume(reservation)
    with sqlite3.connect(ledger) as conn:
        conn.execute('UPDATE account_entry_reservations SET created_at=1')
    restarted = api.AccountOrderAdmission(ledger, collector, fence)
    with pytest.raises(api.AdmissionDenied):
        restarted.reserve(replace(C, credential_fingerprint='rotated', writer_generation=4, intent_digest='b'*64))
    with pytest.raises(api.AdmissionDenied):
        restarted.consume(reservation)


def test_independent_accounts_are_not_blocked(ledger):
    store = api.AccountOrderAdmission(ledger, collector, fence)
    store.reserve(C)
    store.reserve(replace(C, account='kraken:another-account'))


@pytest.mark.parametrize('field,value', [('account', 'other'), ('credential_fingerprint', 'other'),
                                        ('writer_generation', 4), ('intent_digest', 'b'*64)])
def test_reservation_cannot_cross_identity(ledger, field, value):
    store = api.AccountOrderAdmission(ledger, collector, fence)
    reservation = store.reserve(C)
    with pytest.raises(api.AdmissionDenied):
        store.consume(replace(reservation, candidate=replace(C, **{field: value})))


@pytest.mark.parametrize('control', policy.REQUIRED_CONTROLS)
def test_each_check_is_required_again_before_send(ledger, control):
    store = api.AccountOrderAdmission(ledger, collector, fence)
    reservation = store.reserve(C)
    def lost(candidate, conn):
        facts, outcome = collector(candidate, conn)
        facts[control] = replace(facts[control], verified=False)
        return facts, outcome
    store.collector = lost
    with pytest.raises(api.AdmissionDenied, match=control):
        store.consume(reservation)
    with sqlite3.connect(ledger) as conn:
        assert conn.execute('SELECT state FROM account_entry_reservations').fetchone() == ('reserved',)


def test_missing_account_or_ledger_certificate_cannot_reserve(ledger):
    for control in ('authenticated_account', 'ledger_reconciliation'):
        def missing(candidate, conn):
            facts, outcome = collector(candidate, conn)
            del facts[control]
            return facts, outcome
        with pytest.raises(api.AdmissionDenied, match=control):
            api.AccountOrderAdmission(ledger, missing, fence).reserve(C)
    with sqlite3.connect(ledger) as conn:
        assert conn.execute('SELECT COUNT(*) FROM account_entry_reservations').fetchone() == (0,)


def test_collector_cannot_modify_ledger(ledger):
    def writes(candidate, conn):
        conn.execute('DELETE FROM trade_ledger')
        return collector(candidate, conn)
    with pytest.raises(sqlite3.OperationalError):
        api.AccountOrderAdmission(ledger, writes, fence).reserve(C)


def test_writer_loss_after_reservation_denies_consume(ledger):
    store = api.AccountOrderAdmission(ledger, collector, fence)
    reservation = store.reserve(C)
    def lost(candidate):
        raise api.AdmissionDenied('writer_lost')
    store.fence = lost
    with pytest.raises(api.AdmissionDenied, match='writer_lost'):
        store.consume(reservation)


def test_missing_corrupt_and_unmigrated_databases_deny(tmp_path):
    path = tmp_path / 'ledger.db'
    store = api.AccountOrderAdmission(path, collector, fence)
    with pytest.raises(api.AdmissionDenied):
        store.reserve(C)
    assert not path.exists()
    path.write_bytes(b'corrupt')
    with pytest.raises(sqlite3.DatabaseError):
        store.reserve(C)
    path.unlink()
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE unrelated(id INTEGER)')
    with pytest.raises(api.AdmissionDenied, match='schema_missing'):
        store.install_schema()
    with pytest.raises(sqlite3.OperationalError):
        store.reserve(C)
