from __future__ import annotations

import importlib


def _patch():
    return importlib.import_module("bot.runtime_heartbeat_verification_truth_v351_patch")


def _v349():
    return importlib.import_module("bot.runtime_terminal_exit_heartbeat_truth_v349_patch")


def test_ack_timeout_without_order_id_is_not_exchange_rejection():
    p = _patch()
    v349 = _v349()
    assert p._patch_ack_timeout_rejection_truth() is True
    v349._TLS.heartbeat_result = {
        "strategy": "HEARTBEAT_TRADE",
        "status": "error",
        "error": "confirmed_order_rejected:ack_timeout_no_confirmed_fill_within_30s",
        "order_id": "",
    }
    local, reason = v349._proven_local_heartbeat_error("heartbeat_buy_not_accepted status=error")
    assert local is True
    assert "ack_timeout_no_confirmed_fill_within_" in reason


def test_ack_timeout_explicit_rejected_status_still_counts():
    p = _patch()
    v349 = _v349()
    assert p._patch_ack_timeout_rejection_truth() is True
    v349._TLS.heartbeat_result = {
        "strategy": "HEARTBEAT_TRADE",
        "status": "rejected",
        "error": "confirmed_order_rejected:ack_timeout_no_confirmed_fill_within_30s",
        "order_id": "",
    }
    local, reason = v349._proven_local_heartbeat_error("heartbeat_buy_not_accepted status=error")
    assert local is False
    assert reason == "exchange_provenance_present"


def test_ack_timeout_with_order_id_still_counts():
    p = _patch()
    v349 = _v349()
    assert p._patch_ack_timeout_rejection_truth() is True
    v349._TLS.heartbeat_result = {
        "strategy": "HEARTBEAT_TRADE",
        "status": "error",
        "error": "confirmed_order_rejected:ack_timeout_no_confirmed_fill_within_30s",
        "order_id": "EXCHANGE-ORDER-ID",
    }
    local, reason = v349._proven_local_heartbeat_error("heartbeat_buy_not_accepted status=error")
    assert local is False
    assert reason == "exchange_provenance_present"


def test_unknown_heartbeat_failure_remains_fail_closed():
    p = _patch()
    v349 = _v349()
    assert p._patch_ack_timeout_rejection_truth() is True
    v349._TLS.heartbeat_result = {
        "strategy": "HEARTBEAT_TRADE",
        "status": "error",
        "error": "unclassified venue failure",
        "order_id": "",
    }
    local, reason = v349._proven_local_heartbeat_error("heartbeat_buy_not_accepted status=error")
    assert local is False
    assert reason == "unclassified_error"


def test_missing_heartbeat_stage_helper_is_reasserted_without_granting_readiness():
    p = _patch()
    tsm = importlib.import_module("bot.trading_state_machine")
    old = getattr(tsm, "_required_heartbeat_stage", None)
    try:
        if hasattr(tsm, "_required_heartbeat_stage"):
            delattr(tsm, "_required_heartbeat_stage")
        assert not callable(getattr(tsm, "_required_heartbeat_stage", None))
        assert p._repair_heartbeat_stage_helpers() is True
        resolver = getattr(tsm, "_required_heartbeat_stage")
        assert callable(resolver)
        assert str(resolver()).upper() in {"AUTH_VERIFY", "ORDER_VERIFY", "FILL_VERIFY"}
    finally:
        if old is not None:
            setattr(tsm, "_required_heartbeat_stage", old)


def test_manifest_registration_uses_v351_ready_flag():
    p = _patch()
    manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS")
    old = dict(required)
    try:
        assert p._register_manifest() is True
        assert required["runtime_heartbeat_verification_truth_v351"] == p._READY_FLAG
    finally:
        required.clear()
        required.update(old)
