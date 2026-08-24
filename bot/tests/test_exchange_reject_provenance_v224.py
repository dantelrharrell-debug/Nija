from __future__ import annotations

from bot.exchange_kill_switch import ExchangeKillSwitchConfig, ExchangeKillSwitchProtector
from bot import exchange_reject_provenance_v224_patch as v224


def _protector(tmp_path):
    cfg = ExchangeKillSwitchConfig(auto_trigger_enabled=False)
    protector = ExchangeKillSwitchProtector(cfg)
    protector.STATE_FILE = tmp_path / "exchange_kill_switch_state.json"
    protector.reset("v224 test isolation")
    assert v224._patch_record_order_result()
    return protector


def test_synthetic_pipeline_reject_is_ignored_while_global_stop_active(tmp_path, monkeypatch):
    protector = _protector(tmp_path)
    monkeypatch.setattr(protector, "_global_kill_switch_active", lambda: True)

    protector.record_order_result(
        "exec-reject:pipeline:BTC-USD:buy:123",
        accepted=False,
    )

    assert list(protector._order_results) == []


def test_synthetic_pipeline_reject_still_counts_before_global_stop(tmp_path, monkeypatch):
    protector = _protector(tmp_path)
    monkeypatch.setattr(protector, "_global_kill_switch_active", lambda: False)

    protector.record_order_result(
        "exec-reject:pipeline:BTC-USD:buy:124",
        accepted=False,
    )

    assert list(protector._order_results) == [False]


def test_real_exchange_reject_still_counts_while_global_stop_active(tmp_path, monkeypatch):
    protector = _protector(tmp_path)
    monkeypatch.setattr(protector, "_global_kill_switch_active", lambda: True)

    protector.record_order_result("kraken-order-123", accepted=False)

    assert list(protector._order_results) == [False]


def test_accepted_real_order_still_counts(tmp_path, monkeypatch):
    protector = _protector(tmp_path)
    monkeypatch.setattr(protector, "_global_kill_switch_active", lambda: True)

    protector.record_order_result("coinbase-order-456", accepted=True)

    assert list(protector._order_results) == [True]


def test_synthetic_classifier_is_narrow():
    assert v224._is_synthetic_pipeline_reject("exec-reject:pipeline:ETH-USD:buy:1") is True
    assert v224._is_synthetic_pipeline_reject("kraken-exec-reject:pipeline:1") is False
    assert v224._is_synthetic_pipeline_reject("exec-reject:router:ETH-USD") is False
