"""Offline read-only collector tests; synthetic responses are not live proof."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "offline_live_history"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "bot")]
sys.modules[PACKAGE] = package
spec = importlib.util.spec_from_file_location(
    PACKAGE + ".kraken_live_history_recovery", ROOT / "bot/kraken_live_history_recovery.py",
)
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)
NOW = 1000.0
ID = "a" * 32


@pytest.fixture
def root(tmp_path):
    tmp_path.chmod(0o700)
    return tmp_path


def request(root, **changes):
    row = dict(request_id=ID, account_scope="platform:kraken", created_at=NOW, max_pages=2)
    row.update(changes)
    path = root / "request.json"
    path.write_text(json.dumps(row))
    path.chmod(0o600)
    return path


class Broker:
    broker_type = "kraken"
    account_type = "platform"
    user_id = None
    connected = True

    def __init__(self):
        self.calls = []

    def _kraken_private_call(self, endpoint, params, *, category):
        assert category is CATEGORY
        self.calls.append((endpoint, dict(params)))
        if endpoint == "Balance":
            return {"error": [], "result": {"ZUSD": "100"}}
        field = dict(TradesHistory="trades", ClosedOrders="closed", Ledgers="ledger")[endpoint]
        return {"error": [], "result": {"count": 1, field: {"id": {"fee": "1"}}}}


CATEGORY = object()


def run(root, brokers, category=CATEGORY):
    return api.collect_requested_history(root, brokers, monitoring_category=category, now=NOW)


def test_exact_existing_broker_read_only_evidence_and_permanent_claim(root):
    request(root)
    broker = Broker()
    assert run(root, [broker, broker])
    assert len(broker.calls) == 8  # two balances + two full three-endpoint passes
    assert all(e in {"Balance", "TradesHistory", "ClosedOrders", "Ledgers"} for e, _ in broker.calls)
    out = json.loads((root / (ID + ".evidence.json")).read_text())
    assert out["collection_succeeded"] is True and out["trading_authorized"] is False
    assert out["evidence"]["authenticated_identity_independently_verified"] is False
    assert out["evidence"]["ledger_links_verified"] is False
    assert out["evidence"]["atomic_broker_snapshot_verified"] is False
    assert (root / (ID + ".claimed.json")).is_file()
    assert not (root / "request.json").exists()
    assert (root / (ID + ".evidence.json")).stat().st_mode & 0o077 == 0
    request(root)
    with pytest.raises(ValueError, match="replay"):
        run(root, [broker])
    assert len(broker.calls) == 8


@pytest.mark.parametrize("brokers,category", [([], CATEGORY), ([Broker(), Broker()], CATEGORY), ([Broker()], None)])
def test_missing_ambiguous_client_or_enum_performs_no_read(root, brokers, category):
    request(root)
    assert run(root, brokers, category) is False
    assert (root / "request.json").exists()
    assert all(not broker.calls for broker in brokers)


def test_wrong_account_and_disconnected_clients_do_not_read(root):
    request(root, account_scope="user:member:kraken")
    broker = Broker()
    assert not run(root, [broker])
    broker.account_type, broker.user_id, broker.connected = "user", "member", False
    assert not run(root, [broker])
    assert not broker.calls


@pytest.mark.parametrize("changes", [
    {"created_at": 699}, {"created_at": 1001}, {"created_at": True},
    {"created_at": float("nan")}, {"max_pages": True}, {"max_pages": 11},
    {"account_scope": "user: member:kraken"}, {"account_scope": "user::kraken"},
    {"request_id": "../escape"}, {"unknown": True},
])
def test_invalid_request_denied_before_calls(root, changes):
    request(root, **changes)
    broker = Broker()
    with pytest.raises(ValueError):
        run(root, [broker])
    assert not broker.calls


def test_partial_history_is_failure_not_certificate_and_no_automatic_retry(root):
    request(root)
    broker = Broker()
    def fail(*args, **kwargs):
        raise RuntimeError("private upstream credential text must never be persisted")
    broker._kraken_private_call = fail
    assert run(root, [broker])
    output = (root / (ID + ".evidence.json")).read_text()
    assert "private upstream" not in output
    assert json.loads(output) == dict(
        request_id=ID, collection_succeeded=False,
        error_type="RuntimeError", trading_authorized=False,
    )
    assert not run(root, [broker])


def test_process_lock_blocks_duplicate_collection(root):
    request(root)
    with (root / "collector.lock").open("w") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        broker = Broker()
        assert not run(root, [broker])
        assert not broker.calls


def test_private_path_and_request_requirements(root):
    broker = Broker()
    path = request(root)
    path.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        run(root, [broker])
    path.unlink()
    target = root / "target.json"
    target.write_text("{}")
    path.symlink_to(target)
    with pytest.raises(OSError):
        run(root, [broker])
    path.unlink()
    request(root)
    root.chmod(0o755)
    with pytest.raises(ValueError, match="private"):
        run(root, [broker])
    assert not broker.calls


def test_claim_survives_failure_to_persist_output(root, monkeypatch):
    request(root)
    def fail(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(api, "write_recovery_state", fail)
    broker = Broker()
    with pytest.raises(OSError):
        run(root, [broker])
    assert (root / (ID + ".claimed.json")).exists()
    before = len(broker.calls)
    assert not run(root, [broker])
    assert len(broker.calls) == before
