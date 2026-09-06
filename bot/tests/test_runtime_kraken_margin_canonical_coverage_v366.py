from __future__ import annotations

import importlib

import pytest

v366 = importlib.import_module("bot.runtime_kraken_margin_canonical_coverage_v366_patch")


ETH_ROW = {
    "pair": "XETHZUSD",
    "type": "buy",
    "vol": "0.13742703",
    "vol_closed": "0",
    "cost": "343.393906",
    "value": "336.95",
    "margin": "171.696953",
}


class Tracker:
    def __init__(self, holdings=None):
        self.holdings = dict(holdings or {})
        self.mutations = []

    def get_all_positions(self):
        return list(self.holdings)

    def get_position(self, symbol):
        return self.holdings.get(symbol)

    def track_exit(self, symbol):  # pragma: no cover - guard only
        self.mutations.append(symbol)


class Broker:
    def __init__(self, payload=None, *, error=None, holdings=None):
        self.payload = payload
        self.error = error
        self.calls = 0
        self.connected = True
        self.position_tracker = Tracker(holdings)

    def _kraken_api_call(self, method, params=None):
        assert method == "OpenPositions"
        assert (params or {}).get("docalcs") == "true"
        self.calls += 1
        if self.error is not None:
            raise self.error
        payload = self.payload
        return payload(self.calls) if callable(payload) else payload


def _payload(rows):
    return {"error": [], "result": dict(rows)}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("NIJA_KRAKEN_MARGIN_OPENPOSITIONS_TTL_S", "0")
    v366._reset_state_for_tests()
    yield
    v366._reset_state_for_tests()


# A. Open ETH margin long becomes visible to canonical protective coverage.
def test_open_eth_margin_long_visible_in_canonical_coverage():
    broker = Broker(_payload({"TX-1": ETH_ROW}))
    rows, reasons = v366.margin_coverage_rows("platform:kraken", broker)
    assert "kraken_margin_protective_exit_unverified:ETH-USD" in reasons
    assert len(rows) == 1
    row = rows[0]
    assert row["account"] == "platform:kraken"
    assert row["broker"] == "kraken"
    assert row["symbol"] == "ETH-USD"
    assert row["margin_position"] is True
    assert row["source"] == "kraken_open_positions"
    assert row["protective_exit_required"] is True
    assert row["protective_exit_verified"] is False
    assert row["side"] == "long"
    assert row["leverage"] == 2
    assert abs(row["quantity"] - 0.13742703) < 1e-12
    assert abs(row["entry_price"] - (343.393906 / 0.13742703)) < 1e-9
    assert row["exit_protections_attached"] == ()


# B. Margin exposure never enters ordinary spot Balance holdings.
def test_margin_position_not_inserted_into_spot_holdings():
    broker = Broker(_payload({"TX-1": ETH_ROW}))
    rows, _ = v366.margin_coverage_rows("platform:kraken", broker)
    assert rows and rows[0]["spot_holding"] is False
    assert broker.position_tracker.get_all_positions() == []
    assert broker.position_tracker.mutations == []


# C. OpenPositions failure prevents false Kraken READY coverage.
def test_openpositions_failure_blocks_ready(monkeypatch):
    broker = Broker(error=RuntimeError("boom"))
    v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
    monkeypatch.setattr(v281, "_expected_accounts", lambda manager: {"platform:kraken": broker})

    merged = v366.augment_coverage(
        None,
        {"ready": True, "expected_accounts": ("platform:kraken",), "pending": {}, "positions": (),
         "structural_exit_ready": True},
    )
    assert merged["ready"] is False
    reasons = merged["pending"]["platform:kraken"]
    assert any(reason.startswith("kraken_open_positions_fetch_unproven") for reason in reasons)
    assert merged["positions"] == ()


# D. Balance success + OpenPositions failure cannot produce full readiness.
def test_balance_success_cannot_erase_failed_openpositions_proof(monkeypatch):
    broker = Broker(_payload({"TX-1": ETH_ROW}))
    broker.error = RuntimeError("kraken:EService:Unavailable")
    v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
    monkeypatch.setattr(v281, "_expected_accounts", lambda manager: {"platform:kraken": broker})

    balance_ready = {
        "ready": True,
        "expected_accounts": ("platform:kraken",),
        "pending": {},
        "positions": (),
        "structural_exit_ready": True,
    }
    merged = v366.augment_coverage(None, balance_ready)
    assert merged["ready"] is False
    assert "platform:kraken" in merged["pending"]


# E. Protective SELL cannot exceed OpenPositions remaining base quantity.
def test_protective_sell_capped_at_remaining_units():
    broker = Broker(_payload({"TX-1": ETH_ROW}))
    decision = v366.cap_protective_exit_quantity(broker, "ETH-USD", 5.0, account="platform:kraken")
    assert decision["ok"] is True
    assert abs(decision["quantity"] - 0.13742703) < 1e-12
    assert decision["reason"] == "capped"


def test_protective_sell_never_increased_above_request():
    broker = Broker(_payload({"TX-1": ETH_ROW}))
    decision = v366.cap_protective_exit_quantity(broker, "ETH-USD", 0.01, account="platform:kraken")
    assert decision["quantity"] == pytest.approx(0.01)


# F. Partial close reduces authoritative remaining quantity.
def test_partial_close_reduces_remaining_quantity():
    partial = dict(ETH_ROW, vol_closed="0.05")
    broker = Broker(_payload({"TX-1": partial}))
    ok, remaining, reason = v366.authoritative_remaining_units(broker, "XETHZUSD", account="platform:kraken")
    assert ok is True and reason == "ok"
    assert abs(remaining - (0.13742703 - 0.05)) < 1e-12
    decision = v366.cap_protective_exit_quantity(broker, "ETH-USD", 0.13742703, account="platform:kraken")
    assert abs(decision["quantity"] - (0.13742703 - 0.05)) < 1e-12


# G. Fully closed position disappears only after broker evidence.
def test_closed_position_requires_broker_evidence_and_fails_closed_when_unproven():
    payloads = {1: _payload({"TX-1": ETH_ROW}), 2: _payload({})}
    broker = Broker(lambda call: payloads.get(call, _payload({})))
    rows, _ = v366.margin_coverage_rows("platform:kraken", broker)
    assert rows and rows[0]["symbol"] == "ETH-USD"

    # Broker evidence proves the row is gone: the exit fails closed rather than
    # sending a stale SELL, and coverage no longer lists the position.
    decision = v366.cap_protective_exit_quantity(broker, "ETH-USD", 0.13742703, account="platform:kraken")
    assert decision["ok"] is False
    assert decision["reason"] == "margin_position_absent_before_submission"
    rows_after, reasons_after = v366.margin_coverage_rows("platform:kraken", broker)
    assert rows_after == [] and reasons_after == []


def test_unproven_openpositions_blocks_exit_for_known_margin_symbol():
    state = {"fail": False}

    class FlakyBroker(Broker):
        def _kraken_api_call(self, method, params=None):
            if state["fail"]:
                raise RuntimeError("EService:Unavailable")
            return super()._kraken_api_call(method, params)

    broker = FlakyBroker(_payload({"TX-1": ETH_ROW}))
    v366.margin_coverage_rows("platform:kraken", broker)
    state["fail"] = True
    decision = v366.cap_protective_exit_quantity(broker, "ETH-USD", 0.1, account="platform:kraken")
    assert decision["ok"] is False
    assert decision["fail_closed"] is True
    assert decision["reason"] == "kraken_open_positions_fetch_unproven"


# H. OpenPositions never creates fill proof or execution readiness.
def test_openpositions_is_not_fill_proof(monkeypatch):
    monkeypatch.delenv("NIJA_EXECUTION_READY", raising=False)
    broker = Broker(_payload({"TX-1": ETH_ROW}))
    rows, _ = v366.margin_coverage_rows("platform:kraken", broker)
    assert rows[0]["confirmed_fill_proof"] is False
    assert rows[0]["broker_position_state_only"] is True
    import os
    assert os.environ.get("NIJA_EXECUTION_READY") is None


# I/J. Symbol normalisation, including Kraken legacy aliases.
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("XETHZUSD", "ETH-USD"),
        ("ETHUSD", "ETH-USD"),
        ("ETH-USD", "ETH-USD"),
        ("ETH/USD", "ETH-USD"),
        ("XXBTZUSD", "BTC-USD"),
    ],
)
def test_symbol_normalisation(raw, expected):
    assert v366.canonical_symbol(raw) == expected


# K. Multiple Kraken margin positions remain account-isolated.
def test_multiple_accounts_remain_isolated(monkeypatch):
    platform = Broker(_payload({"TX-1": ETH_ROW}))
    user = Broker(_payload({
        "TX-9": {"pair": "XXBTZUSD", "type": "buy", "vol": "0.02", "vol_closed": "0",
                 "cost": "1200", "value": "1210", "margin": "600"},
    }))
    v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
    monkeypatch.setattr(
        v281, "_expected_accounts",
        lambda manager: {"platform:kraken": platform, "user:u1:kraken": user},
    )
    merged = v366.augment_coverage(
        None,
        {"ready": True, "expected_accounts": ("platform:kraken", "user:u1:kraken"),
         "pending": {}, "positions": (), "structural_exit_ready": True},
    )
    by_account = {(row["account"], row["symbol"]) for row in merged["positions"]}
    assert by_account == {("platform:kraken", "ETH-USD"), ("user:u1:kraken", "BTC-USD")}
    assert merged["ready"] is False
    assert set(merged["pending"]) == {"platform:kraken", "user:u1:kraken"}


def test_multiple_lots_for_same_symbol_aggregate_safely():
    broker = Broker(_payload({
        "TX-1": ETH_ROW,
        "TX-2": dict(ETH_ROW, vol="0.1", vol_closed="0", cost="250", value="248", margin="125"),
    }))
    rows, _ = v366.margin_coverage_rows("platform:kraken", broker)
    assert len(rows) == 1
    row = rows[0]
    assert abs(row["quantity"] - (0.13742703 + 0.1)) < 1e-12
    assert abs(row["cost_basis_usd"] - (343.393906 + 250.0)) < 1e-9
    assert row["position_ids"] == ("TX-1", "TX-2")


def test_short_rows_are_not_promoted_as_long_coverage():
    broker = Broker(_payload({
        "TX-1": dict(ETH_ROW, type="sell"),
    }))
    rows, reasons = v366.margin_coverage_rows("platform:kraken", broker)
    assert rows == [] and reasons == []


def test_openpositions_error_payload_is_not_treated_as_empty():
    broker = Broker({"error": ["EAPI:Invalid nonce"], "result": {}})
    ok, positions, reason = v366.fetch_margin_positions(broker, account="platform:kraken")
    assert ok is False and positions == {}
    assert reason.startswith("openpositions_rejected")


def test_non_kraken_accounts_are_ignored(monkeypatch):
    class OKXBroker:
        connected = True

    v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
    monkeypatch.setattr(v281, "_expected_accounts", lambda manager: {"platform:okx": OKXBroker()})
    merged = v366.augment_coverage(
        None,
        {"ready": True, "expected_accounts": ("platform:okx",), "pending": {}, "positions": (),
         "structural_exit_ready": True},
    )
    assert merged["ready"] is True
    assert merged["positions"] == ()


def test_missing_private_api_is_fail_closed():
    class NoApi:
        connected = True

    ok, positions, reason = v366.fetch_margin_positions(NoApi(), account="platform:kraken")
    assert ok is False and positions == {}
    assert reason == "kraken_private_api_unavailable"


# Canonical wiring: the recurring v281 coverage cycle must invoke v366.
def test_install_wires_into_canonical_v281_evaluate_cycle(monkeypatch):
    v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
    original_evaluate = v281.evaluate
    kraken_exit = importlib.import_module("bot.kraken_all_account_exit_runtime_patch")
    original_submit = kraken_exit._submit_exit
    try:
        assert v366._patch_evaluate() is True
        assert v366._patch_exit_submission() is True
        assert getattr(v281.evaluate, v366._PATCH_ATTR, False) is True
        assert getattr(kraken_exit._submit_exit, v366._PATCH_ATTR, False) is True

        broker = Broker(_payload({"TX-1": ETH_ROW}))
        monkeypatch.setattr(v281, "_expected_accounts", lambda manager: {"platform:kraken": broker})
        result = v281.evaluate(None, structural_exit_ready=True)
        symbols = {(row["account"], row["symbol"], row["source"]) for row in result["positions"]}
        assert ("platform:kraken", "ETH-USD", "kraken_open_positions") in symbols
    finally:
        v281.evaluate = original_evaluate
        kraken_exit._submit_exit = original_submit


def test_v366_registered_in_canonical_profitability_chain():
    chain = importlib.import_module("bot.runtime_all_in_profitability_authority_v324_patch")
    source = importlib.import_module("inspect").getsource(chain.install_import_hook)
    assert "bot.runtime_kraken_margin_canonical_coverage_v366_patch" in source
    assert "NIJA_RUNTIME_KRAKEN_MARGIN_CANONICAL_COVERAGE_V366_READY" in source
