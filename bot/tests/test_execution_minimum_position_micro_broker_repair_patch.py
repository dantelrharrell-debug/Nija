from __future__ import annotations

from types import SimpleNamespace

from bot import execution_minimum_position_micro_broker_repair_patch as patch


class FakeMinimumGate:
    def get_minimum_position_size(self, balance):
        return 20.0, 0.05, "INVESTOR"

    def validate_position_size(self, position_size_usd, balance, symbol="UNKNOWN", user_id=None):
        return (
            False,
            f"Position size ${position_size_usd:.2f} below minimum $20.00 (INVESTOR tier, balance ${balance:.2f})",
            {
                "position_size_usd": position_size_usd,
                "balance": balance,
                "min_size_usd": 20.0,
                "tier": "INVESTOR",
                "symbol": symbol,
                "user_id": user_id or "unknown",
            },
        )


class FakeHardening:
    broker_type = "coinbase"

    def validate_order_hardening(self, symbol, side, position_size_usd, balance, current_positions, user_id=None, force_liquidate=False):
        return (
            False,
            f"Position size ${position_size_usd:.2f} below minimum $20.00 (INVESTOR tier, balance ${balance:.2f})",
            {
                "symbol": symbol,
                "side": side,
                "position_size_usd": position_size_usd,
                "balance": balance,
                "position_count": len(current_positions),
                "checks_performed": [
                    {
                        "check": "minimum_position_size",
                        "passed": False,
                        "reason": "below minimum",
                        "details": {
                            "position_size_usd": position_size_usd,
                            "balance": balance,
                            "min_size_usd": 20.0,
                            "tier": "INVESTOR",
                            "symbol": symbol,
                        },
                    }
                ],
            },
        )


def test_minimum_gate_accepts_micro_broker_order_after_platform_tier_inflation(monkeypatch):
    monkeypatch.setenv("NIJA_MICRO_BROKER_MIN_POSITION_REPAIR", "true")
    monkeypatch.setenv("NIJA_MICRO_BROKER_BALANCE_THRESHOLD_USD", "250")
    monkeypatch.setenv("NIJA_MICRO_BROKER_MIN_POSITION_USD", "10")
    monkeypatch.setenv("COINBASE_MIN_ORDER_USD", "1")
    module = SimpleNamespace(ExecutionMinimumPositionGate=FakeMinimumGate, __name__="bot.execution_minimum_position_gate")

    assert patch._patch_minimum_gate(module) is True
    gate = module.ExecutionMinimumPositionGate()

    ok, reason, details = gate.validate_position_size(10.0, 101.63, symbol="AVAX-USD")

    assert ok is True
    assert "micro-broker repair" in reason
    assert details["micro_broker_minimum_repair"] is True
    assert details["original_min_size_usd"] == 20.0


def test_hardening_accepts_only_minimum_position_mismatch(monkeypatch):
    monkeypatch.setenv("NIJA_MICRO_BROKER_MIN_POSITION_REPAIR", "true")
    monkeypatch.setenv("NIJA_MICRO_BROKER_BALANCE_THRESHOLD_USD", "250")
    monkeypatch.setenv("NIJA_MICRO_BROKER_MIN_POSITION_USD", "10")
    monkeypatch.setenv("COINBASE_MIN_ORDER_USD", "1")
    module = SimpleNamespace(ExecutionLayerHardening=FakeHardening, __name__="bot.execution_layer_hardening")

    assert patch._patch_hardening(module) is True
    hardening = module.ExecutionLayerHardening()

    ok, reason, details = hardening.validate_order_hardening(
        "AVAX-USD",
        "buy",
        10.0,
        101.63,
        current_positions=[{"symbol": "BTC-USD"}, {"symbol": "ETH-USD"}],
    )

    assert ok is True
    assert "micro-broker repair" in reason
    assert details["micro_broker_minimum_repair"] is True
    assert details["repair_marker"] == "20260709aa"


def test_hardening_does_not_repair_below_broker_floor(monkeypatch):
    monkeypatch.setenv("NIJA_MICRO_BROKER_MIN_POSITION_REPAIR", "true")
    monkeypatch.setenv("NIJA_MICRO_BROKER_MIN_POSITION_USD", "10")
    module = SimpleNamespace(ExecutionLayerHardening=FakeHardening, __name__="bot.execution_layer_hardening")

    assert patch._patch_hardening(module) is True
    hardening = module.ExecutionLayerHardening()

    ok, reason, details = hardening.validate_order_hardening(
        "AVAX-USD",
        "buy",
        5.0,
        101.63,
        current_positions=[],
    )

    assert ok is False
    assert "below minimum" in reason


def test_hardening_does_not_repair_terminal_or_non_minimum_block(monkeypatch):
    class TerminalHardening:
        broker_type = "coinbase"

        def validate_order_hardening(self, symbol, side, position_size_usd, balance, current_positions, user_id=None, force_liquidate=False):
            return (
                False,
                "Position cap reached",
                {
                    "checks_performed": [
                        {"check": "position_cap", "passed": False, "reason": "Position cap reached"}
                    ]
                },
            )

    module = SimpleNamespace(ExecutionLayerHardening=TerminalHardening, __name__="bot.execution_layer_hardening")
    assert patch._patch_hardening(module) is True
    hardening = module.ExecutionLayerHardening()

    ok, reason, details = hardening.validate_order_hardening("AVAX-USD", "buy", 10.0, 101.63, current_positions=[])

    assert ok is False
    assert reason == "Position cap reached"
