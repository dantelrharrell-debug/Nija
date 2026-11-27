"""Interrupted-process and privacy tests with synthetic broker data only."""
import json
import multiprocessing
import os
import stat

import pytest

from bot.kraken_history_response_journal import PrivateHistoryResponseJournal
from scripts.nija_kraken_readonly_history_collector_v441 import collect_from_existing_broker

IDENTITY = "a" * 32


@pytest.fixture
def root(tmp_path):
    tmp_path.chmod(0o700)
    return tmp_path


def journal(root):
    return PrivateHistoryResponseJournal(root, IDENTITY, "platform:kraken")


def test_exclusive_private_fsynced_archive_has_no_completion_or_authority(root, monkeypatch):
    import bot.kraken_history_response_journal as module

    syncs = []
    real_sync = os.fsync

    def sync(fd):
        syncs.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        real_sync(fd)

    monkeypatch.setattr(module.os, "fsync", sync)
    writer = journal(root)
    writer.append("TradesHistory", {"trades": {"synthetic-fill": {"vol": "1"}}}, 100, 101)
    path = root / (IDENTITY + ".response.000001.json")
    raw = path.read_bytes()
    record = json.loads(raw)
    assert record["result"]["trades"]["synthetic-fill"]["vol"] == "1"
    assert record["request_started_at"] == 100
    assert record["response_finished_at"] == 101
    assert record["complete_collection"] is False
    assert record["response_schema_verified"] is False
    assert record["authenticated_identity_independently_verified"] is False
    assert record["trading_authorized"] is False
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert syncs == [False, True]
    assert not list(root.glob("*.tmp"))
    with pytest.raises(FileExistsError):
        journal(root).append("Balance", {"ZUSD": "999"}, 102, 103)
    assert path.read_bytes() == raw


@pytest.mark.parametrize("endpoint,result,start,end", [
    ("AddOrder", {}, 100, 101), ("CancelOrder", {}, 100, 101),
    ("Balance", [], 100, 101), ("Balance", {}, True, 101),
    ("Balance", {}, 0, 1), ("Balance", {}, 101, 100),
    ("Balance", {}, 100, float("nan")), ("Balance", {"ZUSD": float("inf")}, 100, 101),
])
def test_invalid_input_writes_nothing(root, endpoint, result, start, end):
    with pytest.raises((ValueError, TypeError)):
        journal(root).append(endpoint, result, start, end)
    assert list(root.iterdir()) == []


def test_symlink_and_directory_replacement_cannot_redirect_writes(root, tmp_path_factory):
    writer = journal(root)
    elsewhere = tmp_path_factory.mktemp("other-private")
    elsewhere.chmod(0o700)
    target = elsewhere / "unchanged"
    target.write_text("existing-value")
    (root / (IDENTITY + ".response.000001.json")).symlink_to(target)
    with pytest.raises(FileExistsError):
        writer.append("Balance", {}, 100, 101)
    assert target.read_text() == "existing-value"
    moved = root.with_name(root.name + "-moved")
    root.rename(moved)
    root.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="directory_changed"):
        writer.append("Balance", {}, 100, 101)
    assert list(root.iterdir()) == []


def test_disk_error_stops_archiving_and_removes_temporary(root, monkeypatch):
    import bot.kraken_history_response_journal as module

    def fail(_fd):
        raise OSError("synthetic-disk-error")

    monkeypatch.setattr(module.os, "fsync", fail)
    with pytest.raises(OSError):
        journal(root).append("Balance", {}, 100, 101)
    assert list(root.iterdir()) == []


def test_response_and_total_quotas_stop_new_writes(root, monkeypatch):
    import bot.kraken_history_response_journal as module

    writer = journal(root)
    monkeypatch.setattr(module, "MAX_RESPONSE_BYTES", 1)
    with pytest.raises(ValueError, match="size_limit"):
        writer.append("Balance", {}, 100, 101)
    assert not list(root.iterdir())
    monkeypatch.setattr(module, "MAX_RESPONSE_BYTES", 1024 * 1024)
    writer.append("Balance", {}, 100, 101)
    monkeypatch.setattr(module, "MAX_JOURNAL_BYTES", writer._bytes)
    with pytest.raises(ValueError, match="size_limit"):
        writer.append("Balance", {}, 102, 103)
    assert len(list(root.iterdir())) == 1


class Broker:
    broker_type = "kraken"
    account_type = "platform"
    user_id = None
    connected = True

    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure

    def _kraken_private_call(self, endpoint, params, *, category):
        self.calls.append(endpoint)
        if endpoint == "Balance":
            return {"error": [], "result": {"ZUSD": "100"}}
        if self.failure == "api":
            return {"error": ["untrusted-error-canary"], "result": {}}
        if self.failure == "schema":
            return {"error": [], "result": {"count": True, "trades": {}}}
        field = {"TradesHistory": "trades", "ClosedOrders": "closed", "Ledgers": "ledger"}[endpoint]
        return {"error": [], "result": {"count": 1, field: {"synthetic": {"fee": "1"}}}}


def collect(broker, callback):
    return collect_from_existing_broker(
        broker, account_scope="platform:kraken", monitoring_category=object(),
        include_balance=True, max_pages=1, on_private_response=callback,
    )


def test_callback_mutation_cannot_change_collector_data(root):
    writer = journal(root)

    def callback(endpoint, result, started, finished):
        writer.append(endpoint, result, started, finished)
        result.clear()

    evidence = collect(Broker(), callback)
    assert evidence["history"]["trades"]["synthetic"]["fee"] == "1"
    assert evidence["trading_authorized"] is False
    assert len(list(root.glob("*.response.*.json"))) == 8


def test_api_errors_are_not_archived_and_bad_schema_does_not_certify(root):
    from scripts.nija_kraken_readonly_history_collector_v441 import IncompleteHistory

    with pytest.raises(IncompleteHistory):
        collect(Broker("api"), journal(root).append)
    records = list(root.glob("*.response.*.json"))
    assert len(records) == 1  # Only the earlier successful balance read.
    assert "untrusted-error-canary" not in records[0].read_text()
    other = root / "schema"
    other.mkdir(mode=0o700)
    with pytest.raises(IncompleteHistory):
        collect(Broker("schema"), journal(other).append)
    schema_record = json.loads((other / (IDENTITY + ".response.000002.json")).read_text())
    assert schema_record["response_schema_verified"] is False
    assert schema_record["complete_collection"] is False


def test_failed_persistence_prevents_any_next_broker_read(root):
    broker = Broker()

    def fail(*_args):
        raise OSError("synthetic-disk-error")

    with pytest.raises(OSError):
        collect(broker, fail)
    assert broker.calls == ["Balance"]


def test_account_change_during_read_does_not_archive_other_account_data(root):
    broker = Broker()
    original = broker._kraken_private_call

    def switched(endpoint, params, *, category):
        result = original(endpoint, params, category=category)
        broker.account_type, broker.user_id = "user", "other"
        return result

    broker._kraken_private_call = switched
    with pytest.raises(ValueError, match="scope does not match"):
        collect(broker, journal(root).append)
    assert list(root.iterdir()) == []


def test_shared_directory_and_invalid_callback_deny_before_read(root):
    root.chmod(0o755)
    with pytest.raises(ValueError, match="not_private"):
        journal(root)
    broker = Broker()
    with pytest.raises(ValueError, match="callback must be callable"):
        collect(broker, True)
    assert broker.calls == []


def _interrupted_collection(root):
    from bot.kraken_live_history_recovery import collect_requested_history

    class InterruptedBroker(Broker):
        def _kraken_private_call(self, endpoint, params, *, category):
            if endpoint == "Balance":
                return {"error": [], "result": {"ZUSD": "100"}}
            os._exit(17)

    collect_requested_history(root, [InterruptedBroker()], monitoring_category=object(), now=1000)


def test_process_exit_preserves_returned_response_without_replay_or_certificate(root):
    request = root / "request.json"
    request.write_text(json.dumps({
        "request_id": IDENTITY, "account_scope": "platform:kraken",
        "created_at": 1000, "max_pages": 1,
    }))
    request.chmod(0o600)
    child = multiprocessing.get_context("spawn").Process(target=_interrupted_collection, args=(root,))
    child.start()
    child.join(timeout=10)
    if child.is_alive():
        child.kill()
        child.join(timeout=2)
        pytest.fail("synthetic interrupted collector did not exit")
    assert child.exitcode == 17
    archived = root / (IDENTITY + ".response.000001.json")
    assert json.loads(archived.read_text())["result"] == {"ZUSD": "100"}
    assert (root / (IDENTITY + ".claimed.json")).is_file()
    assert not request.exists()
    assert not (root / (IDENTITY + ".evidence.json")).exists()
    from bot.kraken_live_history_recovery import collect_requested_history

    broker = Broker()
    assert not collect_requested_history(root, [broker], monitoring_category=object(), now=1000)
    assert broker.calls == []
