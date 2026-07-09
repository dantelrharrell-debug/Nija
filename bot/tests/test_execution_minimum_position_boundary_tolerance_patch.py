from __future__ import annotations

from types import SimpleNamespace

from bot import execution_minimum_position_boundary_tolerance_patch as patch


class FakeGate:
    def validate_position_size(self, position_size_usd, balance, symbol="UNKNOWN", user_id=None):
        return (
            False,
            f"Position size ${position_size_usd:.2f} below minimum $10.00 (INVESTOR tier, balance ${balance:.2f})",
            {"min_size_usd": 10.0, "balance": balance},
        )


def test_boundary_equal_size_allowed_with_tolerance():
    module = SimpleNamespace(ExecutionMinimumPositionGate=FakeGate, __name__="bot.execution_minimum_position_gate")
    assert patch._patch_module(module) is True
    gate = module.ExecutionMinimumPositionGate()

    ok, reason, details = gate.validate_position_size(10.0, 101.63, symbol="AXS-USD")

    assert ok is True
    assert "boundary tolerance" in reason
    assert details["boundary_tolerance_applied"] is True


def test_materially_below_minimum_still_blocked():
    module = SimpleNamespace(ExecutionMinimumPositionGate=FakeGate, __name__="bot.execution_minimum_position_gate")
    assert patch._patch_module(module) is True
    gate = module.ExecutionMinimumPositionGate()

    ok, reason, details = gate.validate_position_size(9.50, 101.63, symbol="AXS-USD")

    assert ok is False
    assert "below minimum" in reason
