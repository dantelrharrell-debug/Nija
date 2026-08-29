import time

from bot import runtime_heartbeat_position_cap_failover_v273_patch as v273


class Broker:
    def __init__(self, broker_type):
        self.broker_type = broker_type


class BrokerManager:
    def __init__(self, brokers):
        self.brokers = brokers
        self.active_broker = None

    def get_primary_broker(self):
        return self.brokers.get("coinbase")


class Strategy:
    def __init__(self):
        self.broker_manager = BrokerManager({
            "coinbase": Broker("coinbase"),
            "kraken": Broker("kraken"),
            "okx": Broker("okx"),
        })
        self.multi_account_manager = None
        self.broker = self.broker_manager.brokers["coinbase"]

    def _broker_key_from_obj(self, broker):
        return broker.broker_type

    def _select_entry_broker(self, candidates):
        for name in ("coinbase", "kraken", "okx"):
            if name in candidates:
                return candidates[name], name, "ready"
        return None, None, "none"


def test_hardening_observes_trusted_heartbeat_cap_without_changing_result(monkeypatch):
    v273._clear_cap_block()
    monkeypatch.setattr(v273, "_trusted_heartbeat_probe", lambda: (True, "HEARTBEAT_TRADE"))
    expected = (False, "POSITION_CAP_EXCEEDED: Position cap reached: 2/1 positions", {"x": 1})

    def original(_self, *args, **kwargs):
        return expected

    wrapped = v273._wrap_hardening(original)
    result = wrapped(object(), symbol="BTC-USD", side="BUY")
    assert result is expected
    block = v273._recent_cap_block()
    assert block is not None
    assert block["symbol"] == "BTC-USD"
    assert block["side"] == "BUY"


def test_hardening_does_not_mark_ordinary_order(monkeypatch):
    v273._clear_cap_block()
    monkeypatch.setattr(v273, "_trusted_heartbeat_probe", lambda: (False, "not_heartbeat_thread"))

    def original(_self, *args, **kwargs):
        return (False, "POSITION_CAP_EXCEEDED: Position cap reached", {})

    wrapped = v273._wrap_hardening(original)
    result = wrapped(object(), symbol="BTC-USD", side="BUY")
    assert result[0] is False
    assert v273._recent_cap_block() is None


def test_selector_excludes_cap_and_local_contention_venues(monkeypatch):
    strategy = Strategy()
    monkeypatch.setenv("NIJA_EXECUTION_READY_VENUES", "coinbase,kraken,okx")
    now = time.monotonic()
    strategy._nija_heartbeat_position_cap_until = {"coinbase": now + 60.0}
    strategy._nija_heartbeat_local_busy_until = {"kraken": now + 60.0}

    def original(_self):
        return _self.broker_manager.brokers["coinbase"]

    selected = v273._wrap_selector(original)(strategy)
    assert selected is strategy.broker_manager.brokers["okx"]
    assert strategy.broker is selected
    assert strategy.broker_manager.active_broker is selected


def test_execute_retries_after_cap_block_then_succeeds(monkeypatch):
    strategy = Strategy()
    monkeypatch.setenv("NIJA_EXECUTION_READY_VENUES", "coinbase,kraken,okx")
    monkeypatch.setattr(v273, "_max_fallbacks", lambda: 2)
    calls = {"count": 0}

    def original(_self):
        calls["count"] += 1
        if calls["count"] == 1:
            v273._set_cap_block("POSITION_CAP_EXCEEDED: Position cap reached", symbol="BTC-USD", side="BUY")
            return False
        return True

    wrapped = v273._wrap_execute(original)
    assert wrapped(strategy) is True
    assert calls["count"] == 2
    assert "coinbase" in strategy._nija_heartbeat_position_cap_until


def test_execute_does_not_retry_unrelated_failure(monkeypatch):
    strategy = Strategy()
    monkeypatch.setenv("NIJA_EXECUTION_READY_VENUES", "coinbase,kraken,okx")
    calls = {"count": 0}

    def original(_self):
        calls["count"] += 1
        return False

    wrapped = v273._wrap_execute(original)
    assert wrapped(strategy) is False
    assert calls["count"] == 1
    assert not hasattr(strategy, "_nija_heartbeat_position_cap_until")
