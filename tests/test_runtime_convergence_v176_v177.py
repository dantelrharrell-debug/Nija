from __future__ import annotations

import types

import bot.runtime_capital_reactivation_v176_patch as v176
import bot.runtime_market_data_source_convergence_v177_patch as v177


def test_v177_normalizes_kraken_market_data_symbols():
    assert v177._normalize_symbol("BTC-USD") == "XBTUSD"
    assert v177._normalize_symbol("ETH/USDT") == "ETHUSDT"
    assert v177._normalize_symbol("SOL_USDC") == "SOLUSD"
    assert v177._normalize_symbol("broken") == ""


def test_v177_recognizes_live_kraken_broker_class():
    KrakenBroker = type("KrakenBroker", (), {})
    CoinbaseBroker = type("CoinbaseBroker", (), {})
    assert v177._broker_name(KrakenBroker()) == "kraken"
    assert v177._broker_name(CoinbaseBroker()) == "unknown"


def test_v176_rearm_uses_existing_proof_based_activation(monkeypatch):
    monkeypatch.setattr(v176, "_publication_is_fresh", lambda: (True, "fresh"))

    fake_v16 = types.SimpleNamespace(
        _attempt_activation=lambda: (
            True,
            {
                "pending": [],
                "state_before": "OFF",
                "state_after": "LIVE_ACTIVE",
            },
        )
    )
    original_import = v176.importlib.import_module

    def fake_import(name: str):
        if name == "preactivation_readiness_convergence_v16_patch":
            return fake_v16
        return original_import(name)

    monkeypatch.setattr(v176.importlib, "import_module", fake_import)
    active, reason = v176._rearm_after_publication("test")
    assert active is True
    assert reason == "active"


def test_v176_never_rearms_stale_publication(monkeypatch):
    monkeypatch.setattr(v176, "_publication_is_fresh", lambda: (False, "publication_stale"))
    active, reason = v176._rearm_after_publication("test")
    assert active is False
    assert reason == "publication_stale"


def test_v176_installs_v182_position_fetch_proof(monkeypatch):
    fake_v182 = types.SimpleNamespace(install=lambda: True)
    original_import = v176.importlib.import_module

    def fake_import(name: str):
        if name == "bot.runtime_position_fetch_proof_v182_patch":
            return fake_v182
        return original_import(name)

    monkeypatch.setattr(v176.importlib, "import_module", fake_import)
    assert v176._install_v182_position_fetch_proof() is True
