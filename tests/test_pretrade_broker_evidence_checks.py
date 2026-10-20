"""Focused offline tests for account-scoped read-only reconciliation rules."""
import importlib.util
from pathlib import Path

# Load only the pure rules; package initialization installs runtime hooks.
source = Path(__file__).resolve().parents[1] / "bot" / "pretrade_broker_evidence_checks.py"
spec = importlib.util.spec_from_file_location("offline_broker_evidence", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
reconcile_order_fills = module.reconcile_order_fills
verify_protective_orders = module.verify_protective_orders


def test_fill_reconciliation_rejects_missing_duplicate_and_wrong_account():
    fill = dict(account="platform:kraken", order_id="O-1", trade_id="T-1",
                symbol="ETHUSD", side="buy", quantity="0.1", cost="220", fee="0.5")
    assert reconcile_order_fills("platform:kraken", [fill], [fill])[0]
    assert not reconcile_order_fills("platform:kraken", [fill], [])[0]
    assert not reconcile_order_fills("platform:kraken", [fill, fill], [fill])[0]
    assert not reconcile_order_fills("user:other:kraken", [fill], [fill])[0]


def test_protection_requires_authenticated_reducing_open_order():
    position = dict(account="platform:kraken", symbol="ETHUSD", side="long", quantity="0.1")
    order = dict(account="platform:kraken", symbol="ETHUSD", side="sell",
                 status="open", order_id="O-exit", remaining_quantity="0.1",
                 protective_verified=True, reduce_only_verified=True)
    assert verify_protective_orders("platform:kraken", [position], [order])[0]
    assert not verify_protective_orders("platform:kraken", [position], [])[0]
    assert not verify_protective_orders("platform:kraken", [position],
                                       [{**order, "reduce_only_verified": False}])[0]
    assert not verify_protective_orders("platform:kraken", [position],
                                       [{**order, "remaining_quantity": "0.01"}])[0]


def test_exit_quantity_cannot_be_reused_across_position_lots():
def test_one_exit_cannot_cover_two_positions():
    position = dict(account="platform:kraken", symbol="ETHUSD", side="long", quantity="0.1")
    order = dict(account="platform:kraken", symbol="ETHUSD", side="sell",
                 status="open", order_id="O-exit", remaining_quantity="0.1",
                 protective_verified=True, reduce_only_verified=True)
    assert not verify_protective_orders("platform:kraken", [position, position], [order])[0]
    assert verify_protective_orders("platform:kraken", [position, position],
                                    [{**order, "remaining_quantity": "0.2"}])[0]
    assert not verify_protective_orders("platform:kraken", [position, position], [order, order])[0]
    assert verify_protective_orders("platform:kraken", [position, position],
                                    [order, {**order, "order_id": "O-exit-2"}])[0]


def test_exit_order_identity_cannot_cover_different_assets():
    positions = [dict(account="platform:kraken", symbol=s, side="long", quantity="0.1")
                 for s in ("ETHUSD", "BTCUSD")]
    orders = [dict(account="platform:kraken", symbol=s, side="sell", status="open",
                   order_id="same-id", remaining_quantity="0.1",
                   protective_verified=True, reduce_only_verified=True)
              for s in ("ETHUSD", "BTCUSD")]
    assert not verify_protective_orders("platform:kraken", positions, orders)[0]
    ok, reasons = verify_protective_orders("platform:kraken", [position, position], [order])
    assert not ok
    assert "protective_coverage_insufficient" in reasons
    assert not verify_protective_orders("platform:kraken", [], [])[0]
