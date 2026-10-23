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
        if endpoint == "OpenOrders":
            return {"error": [], "result": {"open": {}}}
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
    assert len(broker.calls) == 10  # balances, history and two current open-order reads
    assert all(e in {"Balance", "TradesHistory", "ClosedOrders", "Ledgers", "OpenOrders"} for e, _ in broker.calls)
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
    assert len(broker.calls) == 10


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
    {"created_at": float("nan")}, {"max_pages": True}, {"max_pages": 101},
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

@pytest.mark.parametrize("scenario,code,endpoint", [
    ("api", "api_failure", "Balance"),
    ("count", "invalid_count", "TradesHistory"),
    ("pages", "page_limit", "TradesHistory"),
])
def test_failed_collection_records_safe_reason_and_keeps_claim(root, caplog, scenario, code, endpoint):
    request(root)
    broker = Broker()
    calls = []

    def read(name, params, *, category):
        calls.append(name)
        assert category is CATEGORY
        if name == "Balance":
            if scenario == "api":
                return {"error": ["sensitive-canary"], "result": {}}
            return {"error": [], "result": {"ZUSD": "100"}}
        assert name == "TradesHistory"
        if scenario == "count":
            return {"error": [], "result": {"count": True, "trades": {}}}
        offset = params["ofs"]
        return {"error": [], "result": {
            "count": 101, "trades": {str(i): {"note": "sensitive-canary"} for i in range(offset, offset + 50)},
        }}

    broker._kraken_private_call = read
    with caplog.at_level("WARNING"):
        assert run(root, [broker])
    raw = (root / (ID + ".evidence.json")).read_text()
    result = json.loads(raw)
    assert result["error_code"] == code
    assert result["error_endpoint"] == endpoint
    assert result["collection_succeeded"] is False
    assert result["trading_authorized"] is False
    assert (root / (ID + ".claimed.json")).exists()
    assert "sensitive-canary" not in raw + caplog.text
    assert "KRAKEN_HISTORY_COLLECTION_FAILED" in caplog.text
    assert len(calls) == {"api": 1, "count": 2, "pages": 2}[scenario]
    assert not run(root, [broker])


def test_unknown_collector_message_is_not_persisted(root, monkeypatch, caplog):
    from scripts.nija_kraken_readonly_history_collector_v441 import IncompleteHistory

    request(root)

    def fail(*args, **kwargs):
        raise IncompleteHistory("TradesHistory: sensitive-canary")

    monkeypatch.setattr(api, "collect_from_existing_broker", fail)
    with caplog.at_level("WARNING"):
        assert run(root, [Broker()])
    raw = (root / (ID + ".evidence.json")).read_text()
    result = json.loads(raw)
    assert result["error_code"] == "history_incomplete_unknown"
    assert "error_endpoint" not in result
    assert "sensitive-canary" not in raw + caplog.text
    assert result["trading_authorized"] is False


def test_exception_subclass_cannot_supply_diagnostic_text():
    from scripts.nija_kraken_readonly_history_collector_v441 import (
        IncompleteHistory, history_failure_diagnostic,
    )

    class UpstreamError(IncompleteHistory):
        def __str__(self):
            raise AssertionError("Upstream exception text must not be inspected")

    assert history_failure_diagnostic(UpstreamError()) == {}


def test_explicit_eleven_page_history_request_retains_fail_closed_authority(root):
    """A larger opt-in history budget must not activate trading."""
    request(root, max_pages=11)
    broker = Broker()
    calls = []

    def read(endpoint, params, *, category):
        assert category is CATEGORY
        calls.append((endpoint, dict(params)))
        if endpoint == "OpenOrders":
            return {"error": [], "result": {"open": {}}}
        if endpoint == "Balance":
            assert params == {}
            return {"error": [], "result": {"ZUSD": "100"}}
        assert set(params) == {"ofs"}
        field = {"TradesHistory": "trades", "ClosedOrders": "closed", "Ledgers": "ledger"}[endpoint]
        count = 501 if endpoint == "TradesHistory" else 0
        offset = params["ofs"]
        batch = {str(i): {"vol": "1"} for i in range(offset, min(count, offset + 50))}
        return {"error": [], "result": {"count": count, field: batch}}

    broker._kraken_private_call = read
    assert run(root, [broker])
    result = json.loads((root / (ID + ".evidence.json")).read_text())
    assert result["collection_succeeded"] is True
    assert len(result["evidence"]["history"]["trades"]) == 501
    assert result["evidence"]["repeat_read_consistent"] is True
    assert result["evidence"]["trading_authorized"] is False
    assert result["evidence"]["authenticated_identity_independently_verified"] is False
    assert result["evidence"]["ledger_links_verified"] is False
    assert result["evidence"]["entry_exit_reconciliation_verified"] is False
    assert result["trading_authorized"] is False
    assert len(calls) == 30  # two balances, 26 history pages and two open-order reads
    assert {endpoint for endpoint, _ in calls} <= {
        "Balance", "TradesHistory", "ClosedOrders", "Ledgers", "OpenOrders"
    }
    assert (root / (ID + ".claimed.json")).exists()
    assert not run(root, [broker])


def test_history_count_exceeding_explicit_budget_stops_on_first_page(root):
    request(root, max_pages=11)
    broker = Broker()
    calls = []

    def read(endpoint, params, *, category):
        assert category is CATEGORY
        calls.append(endpoint)
        if endpoint == "OpenOrders":
            return {"error": [], "result": {"open": {}}}
        if endpoint == "Balance":
            return {"error": [], "result": {"ZUSD": "100"}}
        assert endpoint == "TradesHistory" and params == {"ofs": 0}
        return {"error": [], "result": {"count": 551, "trades": {"first": {"vol": "1"}}}}

    broker._kraken_private_call = read
    assert run(root, [broker])
    result = json.loads((root / (ID + ".evidence.json")).read_text())
    assert result["collection_succeeded"] is False
    assert result["error_code"] == "page_limit"
    assert result["error_endpoint"] == "TradesHistory"
    assert result["required_pages"] == 12
    assert result["requested_pages"] == 11
    assert result["trading_authorized"] is False
    assert calls == ["Balance", "TradesHistory"]
    assert (root / (ID + ".claimed.json")).exists()
    assert not run(root, [broker])


def test_closed_orders_page_budget_reported_only_in_private_receipt(root, caplog):
    request(root, max_pages=11)
    broker = Broker()
    calls = []

    def read(endpoint, params, *, category):
        assert category is CATEGORY
        calls.append((endpoint, dict(params)))
        if endpoint == "Balance":
            return {"error": [], "result": {"ZUSD": "100"}}
        field = {"TradesHistory": "trades", "ClosedOrders": "closed"}[endpoint]
        if endpoint == "TradesHistory":
            return {"error": [], "result": {"count": 0, field: {}}}
        assert endpoint == "ClosedOrders" and params == {"ofs": 0}
        return {"error": [], "result": {"count": 552, field: {"order-id": {"vol": "1"}}}}
def test_open_order_permission_failure_keeps_claim_without_false_certificate(root, caplog):
    request(root)
    broker = Broker()
    original = broker._kraken_private_call

    def read(endpoint, params, *, category):
        if endpoint == "OpenOrders":
            return {"error": ["private-open-order-error-canary"]}
        return original(endpoint, params, category=category)

    broker._kraken_private_call = read
    with caplog.at_level("WARNING"):
        assert run(root, [broker])
    result = json.loads((root / (ID + ".evidence.json")).read_text())
    assert result["collection_succeeded"] is False
    assert result["error_code"] == "page_limit"
    assert result["error_endpoint"] == "ClosedOrders"
    assert result["requested_pages"] == 11
    assert result["required_pages"] == 12
    assert result["trading_authorized"] is False
    assert "552" not in caplog.text
    assert "order-id" not in caplog.text
    assert calls == [
        ("Balance", {}), ("TradesHistory", {"ofs": 0}),
        ("ClosedOrders", {"ofs": 0}),
    ]
    assert (root / (ID + ".claimed.json")).exists()
    assert not run(root, [broker])


def test_unknown_failure_cannot_inject_page_budget(root, monkeypatch):
    from scripts.nija_kraken_readonly_history_collector_v441 import IncompleteHistory
    request(root)

    def fail(*args, **kwargs):
        raise IncompleteHistory(
            "ClosedOrders: untrusted-message",
            required_pages=999999, requested_pages=1,
        )

    monkeypatch.setattr(api, "collect_from_existing_broker", fail)
    assert run(root, [Broker()])
    result = json.loads((root / (ID + ".evidence.json")).read_text())
    assert result["error_code"] == "history_incomplete_unknown"
    assert "required_pages" not in result
    assert "requested_pages" not in result
    assert result["trading_authorized"] is False
    raw = (root / (ID + ".evidence.json")).read_text()
    result = json.loads(raw)
    assert result["collection_succeeded"] is False
    assert result["error_code"] == "api_failure"
    assert result["error_endpoint"] == "OpenOrders"
    assert result["trading_authorized"] is False
    assert "private-open-order-error-canary" not in raw + caplog.text
    assert (root / (ID + ".claimed.json")).exists()
    assert not run(root, [broker])
