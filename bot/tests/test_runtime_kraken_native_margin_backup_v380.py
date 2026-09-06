from types import SimpleNamespace

from bot import runtime_kraken_native_margin_backup_v380_patch as v380


def _row(**overrides):
    row = {
        "symbol": "ETH-USD",
        "quantity": 0.1,
        "remaining_units": 0.1,
        "entry_price": 2500.0,
        "stop_loss": 2475.0,
        "take_profit_1": 2525.0,
        "leverage": 2,
        "side": "long",
        "position_ids": ("P1",),
    }
    row.update(overrides)
    return row


def _install_fake_policy_modules(monkeypatch):
    monkeypatch.setattr(v380, "_v366", lambda: SimpleNamespace(canonical_symbol=lambda value: value))
    monkeypatch.setattr(v380, "_v371", lambda: SimpleNamespace(_ensure_software_targets=lambda row: dict(row)))


def test_native_backup_arms_stop_before_take_profit_and_reproves(monkeypatch):
    _install_fake_policy_modules(monkeypatch)
    monkeypatch.setattr(v380, "_pair_and_price", lambda broker, symbol: ("ETHUSD", 2500.0))
    state = {"stop": False, "tp": False}
    calls = []

    def native_truth(account, broker):
        return True, {
            "ETH-USD": {
                "stop_qty": 0.1 if state["stop"] else 0.0,
                "take_profit_qty": 0.1 if state["tp"] else 0.0,
            }
        }, "ok"

    def submit(broker, *, pair, quantity, leverage, ordertype, trigger, client_id=""):
        calls.append((pair, quantity, leverage, ordertype, trigger, client_id))
        if ordertype == "stop-loss":
            state["stop"] = True
        elif ordertype == "take-profit":
            state["tp"] = True
        return True, ("TX-" + ordertype,), "ok"

    monkeypatch.setattr(v380, "_native_truth", native_truth)
    monkeypatch.setattr(v380, "_submit_reduce_only", submit)
    proof = v380._arm_position("platform:kraken", object(), _row())

    assert proof["native_backup_verified"] is True
    assert [call[3] for call in calls] == ["stop-loss", "take-profit"]
    assert calls[0][1] == 0.1
    assert calls[0][2] == 2
    assert calls[0][5].startswith("njsl")
    assert calls[1][5].startswith("njtp")
    assert len(calls[0][5]) <= 18
    assert len(calls[1][5]) <= 18


def test_crossed_trigger_never_parks_stale_native_order(monkeypatch):
    _install_fake_policy_modules(monkeypatch)
    monkeypatch.setattr(v380, "_pair_and_price", lambda broker, symbol: ("ETHUSD", 2470.0))
    calls = []
    monkeypatch.setattr(v380, "_submit_reduce_only", lambda *args, **kwargs: calls.append(kwargs))

    proof = v380._arm_position("platform:kraken", object(), _row())
    assert proof["native_backup_verified"] is False
    assert proof["reason"] == "trigger_already_crossed_software_exit_owns_due_action"
    assert calls == []


def test_short_position_fails_closed_without_submission(monkeypatch):
    _install_fake_policy_modules(monkeypatch)
    calls = []
    monkeypatch.setattr(v380, "_submit_reduce_only", lambda *args, **kwargs: calls.append(kwargs))
    proof = v380._arm_position("platform:kraken", object(), _row(side="short"))
    assert proof["native_backup_verified"] is False
    assert proof["reason"] == "short_native_backup_not_enabled_v380"
    assert calls == []


def test_submit_payload_is_sell_reduce_only_and_client_tagged(monkeypatch):
    captured = {}

    class Broker:
        def _kraken_private_call(self, method, params=None, category=None):
            captured["method"] = method
            captured["params"] = dict(params or {})
            return {"error": [], "result": {"txid": ["ORDER1"]}}

    monkeypatch.setattr(v380, "_private_call", lambda broker: broker._kraken_private_call)
    client_id = v380._client_id("platform:kraken", "ETH-USD", "stop-loss")
    ok, txids, reason = v380._submit_reduce_only(
        Broker(), pair="ETHUSD", quantity=0.1, leverage=2,
        ordertype="stop-loss", trigger=2475.0, client_id=client_id,
    )
    assert ok is True
    assert txids == ("ORDER1",)
    assert reason == "ok"
    assert captured["method"] == "AddOrder"
    assert captured["params"]["type"] == "sell"
    assert captured["params"]["reduce_only"] is True
    assert captured["params"]["leverage"] == "2"
    assert captured["params"]["ordertype"] == "stop-loss"
    assert captured["params"]["cl_ord_id"] == client_id


def test_orphan_cleanup_cancels_only_matching_nija_native_order(monkeypatch):
    _install_fake_policy_modules(monkeypatch)
    account = "platform:kraken"
    stale_id = v380._client_id(account, "ETH-USD", "stop-loss")
    calls = []

    def private_call(broker, method, params, category_name):
        calls.append((method, dict(params)))
        if method == "OpenOrders":
            return {
                "error": [],
                "result": {
                    "open": {
                        "N1": {"cl_ord_id": stale_id, "descr": {"pair": "ETH-USD"}},
                        "OTHER": {"cl_ord_id": "manual-order", "descr": {"pair": "ETH-USD"}},
                    }
                },
            }
        if method == "CancelOrder":
            return {"error": [], "result": {"count": 1}}
        raise AssertionError(method)

    monkeypatch.setattr(v380, "_call", private_call)
    cancelled = v380._cleanup_orphans(account, object(), set())
    assert cancelled == ("N1",)
    cancel_calls = [params for method, params in calls if method == "CancelOrder"]
    assert cancel_calls == [{"txid": "N1"}]
