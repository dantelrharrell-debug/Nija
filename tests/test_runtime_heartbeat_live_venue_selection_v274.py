from __future__ import annotations

import os
import threading

import bot.runtime_heartbeat_live_venue_selection_v274_patch as v274


class _Broker:
    def __init__(self, name: str, balance: float = 50.0) -> None:
        self.broker_type = name
        self.connected = True
        self._last_known_balance = float(balance)
        self.live_reads = 0

    def get_account_balance(self):
        self.live_reads += 1
        raise AssertionError("v322 funded selection must not start broker I/O")


class _Strategy:
    def __init__(self, *, coinbase: float = 50.0, kraken: float = 50.0) -> None:
        self.broker = None
        self.coinbase = _Broker("coinbase", coinbase)
        self.kraken = _Broker("kraken", kraken)
        self.multi_account_manager = type(
            "M",
            (),
            {"platform_brokers": {"c": self.coinbase, "k": self.kraken}},
        )()
        self.broker_manager = None

    @staticmethod
    def _balance_from_payload(payload):
        return float(payload)

    @staticmethod
    def _broker_key_from_obj(broker):
        return str(getattr(broker, "broker_type", "") or "").lower()

    @staticmethod
    def _resolve_heartbeat_trade_amount_usd(_broker):
        return 12.50

    def _select_entry_broker(self, candidates):
        for wanted in ("coinbase", "kraken"):
            for broker in candidates.values():
                if getattr(broker, "broker_type", None) == wanted:
                    return broker, wanted, {wanted: "ok"}
        return None, None, {"all": "none"}


def _on_heartbeat(fn):
    out = []
    thread = threading.Thread(target=lambda: out.append(fn()), name="HeartbeatTrade")
    thread.start()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    return out[0]


def _reset_env() -> None:
    for key in (
        "NIJA_EXECUTION_READY_VENUES",
        "NIJA_GLOBAL_TRADING_READY",
        "NIJA_ACTIVE_LIVE_VENUES",
    ):
        os.environ.pop(key, None)


def test_v274_requires_canonical_readiness_publication():
    _reset_env()
    assert _on_heartbeat(lambda: v274._live_venue_fallback_set()[0]) is False


def test_v274_never_overrides_nonempty_canonical_ready_set():
    _reset_env()
    os.environ["NIJA_EXECUTION_READY_VENUES"] = "coinbase"
    os.environ["NIJA_GLOBAL_TRADING_READY"] = "1"
    os.environ["NIJA_ACTIVE_LIVE_VENUES"] = "coinbase,kraken"
    assert _on_heartbeat(lambda: v274._live_venue_fallback_set()[0]) is False


def test_v274_empty_canonical_set_is_heartbeat_thread_only():
    _reset_env()
    os.environ["NIJA_EXECUTION_READY_VENUES"] = ""
    os.environ["NIJA_GLOBAL_TRADING_READY"] = "1"
    os.environ["NIJA_ACTIVE_LIVE_VENUES"] = "coinbase,kraken"
    assert v274._live_venue_fallback_set()[0] is False
    assert _on_heartbeat(v274._live_venue_fallback_set) == (
        True,
        ("coinbase", "kraken"),
        "broker_local_selection_only",
    )


def test_v274_wrapper_preserves_original_selection_success():
    _reset_env()
    strategy = _Strategy(coinbase=0.0, kraken=0.0)
    expected = _Broker("okx", 0.0)
    wrapped = v274._wrap_selector(lambda self: expected)
    assert wrapped(strategy) is expected


def test_v322_skips_underfunded_active_venue_and_uses_funded_one():
    _reset_env()
    os.environ["NIJA_EXECUTION_READY_VENUES"] = ""
    os.environ["NIJA_GLOBAL_TRADING_READY"] = "1"
    os.environ["NIJA_ACTIVE_LIVE_VENUES"] = "coinbase,kraken"
    strategy = _Strategy(coinbase=8.22, kraken=50.0)
    wrapped = v274._wrap_selector(lambda self: None)
    selected = _on_heartbeat(lambda: wrapped(strategy))
    assert selected is strategy.kraken
    assert strategy.coinbase.live_reads == 0
    assert strategy.kraken.live_reads == 0


def test_v322_fails_closed_when_no_active_venue_can_fund_heartbeat():
    _reset_env()
    os.environ["NIJA_EXECUTION_READY_VENUES"] = ""
    os.environ["NIJA_GLOBAL_TRADING_READY"] = "1"
    os.environ["NIJA_ACTIVE_LIVE_VENUES"] = "coinbase,kraken"
    strategy = _Strategy(coinbase=8.22, kraken=10.89)
    wrapped = v274._wrap_selector(lambda self: None)
    selected = _on_heartbeat(lambda: wrapped(strategy))
    assert selected is None
    assert strategy.coinbase.live_reads == 0
    assert strategy.kraken.live_reads == 0


def test_v274_wrapper_uses_only_broker_local_active_venue_when_funded():
    _reset_env()
    os.environ["NIJA_EXECUTION_READY_VENUES"] = ""
    os.environ["NIJA_GLOBAL_TRADING_READY"] = "1"
    os.environ["NIJA_ACTIVE_LIVE_VENUES"] = "kraken"
    strategy = _Strategy(coinbase=50.0, kraken=50.0)
    wrapped = v274._wrap_selector(lambda self: None)
    selected = _on_heartbeat(lambda: wrapped(strategy))
    assert selected is not None
    assert selected.broker_type == "kraken"
    assert strategy.kraken.live_reads == 0
