from __future__ import annotations

from types import SimpleNamespace


def test_symbol_absence_recovers_only_on_exact_jit_quantity(monkeypatch):
    from bot import runtime_exit_jit_conflict_recovery_v332_patch as v332
    from bot import runtime_universal_exit_tracker_convergence_v323_patch as v323
    from bot import runtime_capital_recycling_exit_v330_patch as v330

    original = v323._position_exit_proof
    monkeypatch.setattr(
        v323,
        "_position_exit_proof",
        lambda universal, broker, pos: (
            False,
            "symbol_absent_from_recent_authoritative_snapshot",
            {},
        ),
    )
    monkeypatch.setattr(v330, "_jit_quantity", lambda broker, symbol: (True, 2.0, "broker_get_positions", 0.2))
    monkeypatch.setattr(v330, "_quantity_matches", lambda left, right: abs(left - right) < 1e-12)

    universal = SimpleNamespace(
        auto_exit=SimpleNamespace(
            _sym=lambda value: value,
            _quantity=lambda pos: float(pos["quantity"]),
            _broker_label=lambda broker: "coinbase",
        ),
        _account_label=lambda broker: "platform",
    )
    assert v332._patch_v323_conflicts() is True
    safe, reason, details = v323._position_exit_proof(
        universal,
        SimpleNamespace(),
        {"symbol": "ETH-USD", "quantity": 2.0},
    )
    assert safe is True
    assert reason == "verified_jit_conflict_recovery"
    assert details["jit_authoritative_quantity"] == 2.0

    monkeypatch.setattr(v323, "_position_exit_proof", original)


def test_quantity_conflict_remains_blocked_when_jit_disagrees(monkeypatch):
    from bot import runtime_exit_jit_conflict_recovery_v332_patch as v332
    from bot import runtime_universal_exit_tracker_convergence_v323_patch as v323
    from bot import runtime_capital_recycling_exit_v330_patch as v330

    original = v323._position_exit_proof
    monkeypatch.setattr(
        v323,
        "_position_exit_proof",
        lambda universal, broker, pos: (False, "authoritative_quantity_mismatch", {}),
    )
    monkeypatch.setattr(v330, "_jit_quantity", lambda broker, symbol: (True, 1.5, "broker_get_positions", 0.1))
    monkeypatch.setattr(v330, "_quantity_matches", lambda left, right: abs(left - right) < 1e-12)

    universal = SimpleNamespace(
        auto_exit=SimpleNamespace(
            _sym=lambda value: value,
            _quantity=lambda pos: float(pos["quantity"]),
            _broker_label=lambda broker: "coinbase",
        ),
        _account_label=lambda broker: "platform",
    )
    assert v332._patch_v323_conflicts() is True
    safe, reason, details = v323._position_exit_proof(
        universal,
        SimpleNamespace(),
        {"symbol": "ETH-USD", "quantity": 2.0},
    )
    assert safe is False
    assert reason == "jit_conflict_quantity_mismatch"
    assert details["jit_authoritative_quantity"] == 1.5

    monkeypatch.setattr(v323, "_position_exit_proof", original)
