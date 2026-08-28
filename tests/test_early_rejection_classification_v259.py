from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "bot" / "exchange_kill_switch_internal_reject_guard_patch.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("test_early_rejection_guard_v259", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v259_early_classifier_matches_known_local_predispatch_blocks():
    guard = _load_module()
    local_reasons = (
        "dispatch_disabled: dispatch.enabled=false",
        "execution_authority_halt:writer unavailable",
        "state_machine=live_pending_confirmation",
        "ExchangeKillSwitch: exchange health red — trade blocked",
        "LiquidityIntelligenceEngine: liquidity grade below minimum",
        "no available venue found for BTC-USD",
        "PreTradeRiskEngine reject: exposure cap",
        "RiskGovernor blocked: drawdown guard",
        "SlippageGuard blocked: spread too wide",
        "CapitalAuthorization deny: stale capital",
        "MarginHealthGate reject: margin unavailable",
        "ECEL unavailable for symbol",
        "OrderFeasibility deny: min notional",
        "broker_dispatch_failed: local adapter path",
        "empty_order_result",
        "broker disabled",
        "adapter_exception: local failure",
        "confirmed_order_rejected:ack_timeout",
        "terminal_reject_status:unfilled",
    )
    for reason in local_reasons:
        assert guard._soft_non_exchange_reason(reason) is True, reason


def test_v259_genuine_or_unknown_exchange_rejects_are_not_suppressed():
    guard = _load_module()
    genuine_or_unknown = (
        "Coinbase order rejected: insufficient liquidity",
        "Kraken EOrder:Insufficient funds",
        "OKX order rejected by exchange: 51008",
        "unknown exchange rejection",
        "HTTP 400 exchange response: invalid order",
    )
    for reason in genuine_or_unknown:
        assert guard._soft_non_exchange_reason(reason) is False, reason
