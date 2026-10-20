from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from bot import runtime_kraken_client_order_recovery_v430_patch as v430


class _Broker:
    account_identifier = "platform"

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def _kraken_private_call(self, method, params=None, *args, **kwargs):
        self.calls.append((method, dict(params or {}), args, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    path = tmp_path / "client-refs.json"
    monkeypatch.setattr(v430, "_state_path", lambda: path)
    return path


def test_addorder_binds_durable_client_id_and_hands_returned_txid_to_v363(state_path, monkeypatch):
    broker_cls = type("KrakenBrokerForV430", (_Broker,), {})
    assert v430._patch_class(broker_cls) is True

    seeded = []
    monkeypatch.setattr(
        v430,
        "_seed_txids",
        lambda txids, **meta: seeded.append((txids, meta)) or len(txids),
    )
    broker = broker_cls(response={"error": [], "result": {"txid": ["OID-430"]}})
    response = broker._kraken_private_call(
        "AddOrder",
        {"pair": "XETHZUSD", "type": "buy", "ordertype": "market", "volume": "0.01"},
    )

    assert response["result"]["txid"] == ["OID-430"]
    submitted = broker.calls[0][1]
    client_id = submitted["cl_ord_id"]
    assert client_id.startswith("nj")
    assert len(client_id) == 18
    assert seeded == [
        (("OID-430",), {"pair": "XETHZUSD", "side": "buy", "status": "ack"})
    ]
    assert v430._load_refs() == {}


def test_lost_addorder_response_retains_client_id_for_read_only_recovery(state_path):
    broker_cls = type("KrakenBrokerTimeoutV430", (_Broker,), {})
    assert v430._patch_class(broker_cls) is True
    broker = broker_cls(error=TimeoutError("response lost"))

    with pytest.raises(TimeoutError, match="response lost"):
        broker._kraken_private_call(
            "AddOrder",
            {"pair": "XETHZUSD", "type": "buy", "ordertype": "market", "volume": "0.01"},
        )

    refs = v430._load_refs()
    assert len(refs) == 1
    client_id, entry = next(iter(refs.items()))
    assert client_id.startswith("nj")
    assert entry["account"] == "platform"
    assert entry["pair"] == "XETHZUSD"
    assert entry["side"] == "buy"


def test_existing_client_id_is_never_replaced_or_registered(state_path):
    broker_cls = type("KrakenBrokerExistingIdV430", (_Broker,), {})
    assert v430._patch_class(broker_cls) is True
    broker = broker_cls(response={"error": [], "result": {"txid": ["OID-EXISTING"]}})

    broker._kraken_private_call(
        "AddOrder",
        {
            "pair": "XETHZUSD",
            "type": "sell",
            "ordertype": "stop-loss",
            "volume": "0.01",
            "cl_ord_id": "existing-protect-1",
        },
    )

    assert broker.calls[0][1]["cl_ord_id"] == "existing-protect-1"
    assert v430._load_refs() == {}


def test_exact_client_filter_adopts_one_closed_order_only(monkeypatch):
    broker = object()
    seen = []

    class _V357:
        @staticmethod
        def _private_read(_broker, method, params):
            seen.append((method, dict(params)))
            if method == "ClosedOrders":
                return {
                    "error": [],
                    "result": {
                        "closed": {
                            "OID-CLOSED": {
                                "status": "closed",
                                "descr": {"type": "buy"},
                                "vol_exec": "0.01",
                                "cost": "25",
                            }
                        }
                    },
                }
            return {"error": [], "result": {"open": {}}}

    original = v430.importlib.import_module
    monkeypatch.setattr(
        v430.importlib,
        "import_module",
        lambda name: _V357 if name == "bot.runtime_kraken_delayed_fill_reconciliation_v357_patch" else original(name),
    )

    order_id, row, source = v430._exact_client_row(broker, "nj123")
    assert order_id == "OID-CLOSED"
    assert row["status"] == "closed"
    assert source == "closedorders"
    assert seen == [("ClosedOrders", {"trades": True, "cl_ord_id": "nj123"})]


def test_ambiguous_client_filter_never_adopts_txid(monkeypatch):
    class _V357:
        @staticmethod
        def _private_read(_broker, method, params):
            return {
                "error": [],
                "result": {
                    "closed": {
                        "OID-1": {"status": "closed"},
                        "OID-2": {"status": "closed"},
                    }
                },
            }

    original = v430.importlib.import_module
    monkeypatch.setattr(
        v430.importlib,
        "import_module",
        lambda name: _V357 if name == "bot.runtime_kraken_delayed_fill_reconciliation_v357_patch" else original(name),
    )

    order_id, row, reason = v430._exact_client_row(object(), "nj-ambiguous")
    assert order_id == ""
    assert row == {}
    assert reason == "ambiguous_client_id_result"


def test_recovery_hands_exact_client_id_txid_to_v363_and_clears_ref(state_path, monkeypatch):
    broker = SimpleNamespace(account_identifier="platform")
    assert v430.record_pending_client_ref(
        client_id="nj1234567890123456",
        broker=broker,
        pair="XETHZUSD",
        side="buy",
        ordertype="market",
    )

    fake_v363 = SimpleNamespace(
        _kraken_brokers=lambda: [broker],
        recover_once=lambda: 0,
    )
    original = v430.importlib.import_module
    monkeypatch.setattr(
        v430.importlib,
        "import_module",
        lambda name: fake_v363 if name == "bot.runtime_kraken_deferred_fill_proof_recovery_v363_patch" else original(name),
    )
    monkeypatch.setattr(
        v430,
        "_exact_client_row",
        lambda _broker, cid: (
            "OID-RECOVERED",
            {"status": "closed", "descr": {"type": "buy"}},
            "closedorders",
        ),
    )

    seeded = []
    monkeypatch.setattr(
        v430,
        "_seed_txids",
        lambda txids, **meta: seeded.append((txids, meta)) or 1,
    )

    assert v430.recover_client_refs_once() == 1
    assert seeded == [
        (("OID-RECOVERED",), {"pair": "XETHZUSD", "side": "buy", "status": "closed"})
    ]
    assert v430._load_refs() == {}


def test_v430_is_wired_into_canonical_profitability_chain():
    from pathlib import Path

    chain = Path("bot/runtime_all_in_profitability_authority_v324_patch.py").read_text(encoding="utf-8")
    assert '"v430", "bot.runtime_kraken_client_order_recovery_v430_patch"' in chain
    assert '"NIJA_RUNTIME_KRAKEN_CLIENT_ORDER_RECOVERY_V430_READY"' in chain


@pytest.mark.parametrize("failure", [OSError("disk full"), PermissionError("read only")])
def test_persistence_failure_prevents_actual_broker_call(state_path, monkeypatch, failure):
    broker_cls = type("KrakenPersistenceFailure", (_Broker,), {})
    v430._patch_class(broker_cls)
    broker = broker_cls(response={"error": [], "result": {"txid": ["OID"]}})

    def fail(*args):
        raise failure

    monkeypatch.setattr(v430, "write_recovery_state", fail)
    with pytest.raises(OSError):
        broker._kraken_private_call("AddOrder", {"pair": "XETHZUSD", "type": "buy"})
    assert broker.calls == []


def test_corrupt_state_blocks_submit_without_overwriting(state_path):
    state_path.write_text('{broken')
    broker_cls = type("KrakenCorruptState", (_Broker,), {})
    v430._patch_class(broker_cls)
    broker = broker_cls()
    with pytest.raises(ValueError):
        broker._kraken_private_call("AddOrder", {"pair": "XETHZUSD", "type": "buy"})
    assert not broker.calls
    assert state_path.read_text() == '{broken'


def test_failed_txid_handoff_retains_exact_client_id(state_path, monkeypatch):
    broker_cls = type("KrakenFailedHandoff", (_Broker,), {})
    v430._patch_class(broker_cls)
    monkeypatch.setattr(v430, "_seed_txids", lambda *a, **k: 0)
    broker = broker_cls(response={"error": [], "result": {"txid": ["OID"]}})
    broker._kraken_private_call("AddOrder", {"pair": "XETHZUSD", "type": "buy"})
    assert broker.calls[0][1]["cl_ord_id"] in v430._load_refs()


def test_validate_only_never_claims_a_real_submission(state_path):
    broker_cls = type("KrakenValidateOnly", (_Broker,), {})
    v430._patch_class(broker_cls)
    broker = broker_cls(response={"error": [], "result": {"descr": {}}})
    broker._kraken_private_call("AddOrder", {"validate": True, "pair": "XETHZUSD"})
    assert "cl_ord_id" not in broker.calls[0][1]
    assert not state_path.exists()


def test_pending_capacity_never_evicts_an_unresolved_order(state_path, monkeypatch):
    monkeypatch.setattr(v430, "_MAX_PENDING", 1)
    assert v430.record_pending_client_ref(client_id="original", broker=_Broker(), pair="XETHZUSD")
    before = state_path.read_bytes()
    broker_cls = type("KrakenCapacity", (_Broker,), {})
    v430._patch_class(broker_cls)
    broker = broker_cls()
    with pytest.raises(RuntimeError, match="capacity"):
        broker._kraken_private_call("AddOrder", {"pair": "XETHZUSD"})
    assert not broker.calls
    assert state_path.read_bytes() == before


def test_real_handoff_write_failure_keeps_recovery_identity(state_path, tmp_path, monkeypatch):
    from bot import runtime_kraken_deferred_fill_proof_recovery_v363_patch as v363
    monkeypatch.setattr(v363, "_state_path", lambda: tmp_path / "pending-fills.json")

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(v363, "write_recovery_state", fail)
    broker_cls = type("KrakenActualHandoff", (_Broker,), {})
    v430._patch_class(broker_cls)
    broker = broker_cls(response={"error": [], "result": {"txid": ["OID"]}})
    broker._kraken_private_call("AddOrder", {"pair": "XETHZUSD", "type": "buy"})
    assert broker.calls[0][1]["cl_ord_id"] in v430._load_refs()
