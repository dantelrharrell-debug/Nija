from __future__ import annotations

import importlib
import threading
from types import SimpleNamespace


def _patch():
    return importlib.import_module("bot.runtime_terminal_exit_heartbeat_truth_v349_patch")


def test_protective_exit_detection_requires_verified_sell_close():
    p = _patch()
    req = SimpleNamespace(
        side="sell",
        intent_type="exit",
        position_effect="close",
        metadata={"verified_position_quantity": 35.34862, "origin": "universal_v67"},
    )
    is_exit, verified, origin = p._protective_exit(req)
    assert is_exit is True
    assert abs(verified - 35.34862) < 1e-9
    assert origin == "universal_v67"

    entry = SimpleNamespace(
        side="buy",
        intent_type="entry",
        metadata={"verified_position_quantity": 35.34862},
    )
    assert p._protective_exit(entry)[0] is False


def test_local_heartbeat_defer_requires_pipeline_provenance_without_order_id():
    p = _patch()
    p._TLS.heartbeat_result = {
        "strategy": "HEARTBEAT_TRADE",
        "status": "error",
        "error": "Execution quality filter DEFERRED (score=52.5, retry_in=165s)",
        "order_id": "",
    }
    local, _ = p._proven_local_heartbeat_error("heartbeat_buy_not_accepted status=error")
    assert local is True


def test_unknown_heartbeat_error_stays_fail_closed_and_counts_as_rejection():
    p = _patch()
    p._TLS.heartbeat_result = {
        "strategy": "HEARTBEAT_TRADE",
        "status": "error",
        "error": "unclassified venue failure",
        "order_id": "",
    }
    local, reason = p._proven_local_heartbeat_error("heartbeat_buy_not_accepted status=error")
    assert local is False
    assert reason == "unclassified_error"


def test_explicit_exchange_rejection_is_never_suppressed():
    p = _patch()
    p._TLS.heartbeat_result = {
        "strategy": "HEARTBEAT_TRADE",
        "status": "rejected",
        "error": "exchange rejected order",
        "order_id": "",
    }
    local, reason = p._proven_local_heartbeat_error("heartbeat_buy_not_accepted status=error")
    assert local is False
    assert reason == "exchange_provenance_present"


def test_order_id_is_never_reclassified_as_local_defer():
    p = _patch()
    p._TLS.heartbeat_result = {
        "strategy": "HEARTBEAT_TRADE",
        "status": "error",
        "error": "Execution gate pending",
        "order_id": "KRAKEN-REAL-ID",
    }
    local, reason = p._proven_local_heartbeat_error("heartbeat_buy_not_accepted status=error")
    assert local is False
    assert reason == "exchange_provenance_present"


def test_terminal_firewall_blocks_ecel_upsize_above_verified_holdings(monkeypatch):
    p = _patch()
    ep = importlib.import_module("bot.execution_pipeline")
    assert p._patch_pipeline_terminal_firewall() is True

    # Avoid constructing the heavyweight pipeline; the patched gate needs only
    # the original capability gate when the firewall allows.  In this case it
    # must return before that boundary because ECEL enlarged 35.34862 -> 70.
    obj = object.__new__(ep.ExecutionPipeline)
    req = ep.PipelineRequest(
        strategy="protective_exit",
        symbol="CELO-USD",
        side="sell",
        size_usd=5.39,
        price_hint_usd=0.077,
        account_id="tania_gilbert",
        metadata={
            "verified_position_quantity": 35.34862,
            "origin": "universal_v67",
            "intent_type": "exit",
            "position_effect": "close",
        },
    )
    with p._COMPILED_LOCK:
        p._COMPILED[id(req)] = (70.0, 0.077, "accepted")
    result = ep.ExecutionPipeline._gate_broker_capabilities(obj, req, 0.0)
    assert result.success is False
    assert "EXIT_BELOW_EXCHANGE_MIN_AFTER_HOLDINGS_CAP" in result.error
    assert "oversell_blocked=true" in result.error


def test_manifest_registration_uses_v349_ready_flag(monkeypatch):
    p = _patch()
    manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS")
    old = dict(required)
    try:
        assert p._register_manifest() is True
        assert required["runtime_terminal_exit_heartbeat_truth_v349"] == p._READY_FLAG
    finally:
        required.clear()
        required.update(old)
