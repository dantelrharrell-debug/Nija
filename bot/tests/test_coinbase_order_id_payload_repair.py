"""Tests for Coinbase order-ID payload repair.

COINBASE_ORDER_ID_PAYLOAD_REPAIRED marker=20260709ap

Verifies that _normalize_coinbase_result() promotes nested Coinbase order_id /
fill fields to the top-level result dict so that _looks_confirmed_fill() can
correctly classify confirmed fills without loosening execution gates.
"""
from __future__ import annotations

from bot import direct_broker_venue_cash_hard_gate_patch as patch


# ---------------------------------------------------------------------------
# _normalize_coinbase_result – order_id promotion paths
# ---------------------------------------------------------------------------

def test_nested_order_success_response_order_id_is_promoted():
    """order.success_response.order_id must be copied to top-level order_id."""
    result = {
        "status": "filled",
        "order": {
            "success_response": {
                "order_id": "real-cb-uuid-abc123",
                "average_filled_price": "0.4500",
                "filled_size": "50.0",
            }
        },
        "filled_size": 50.0,
    }
    patch._normalize_coinbase_result(result, size_usd=22.5)

    assert result["order_id"] == "real-cb-uuid-abc123"
    assert result["filled_price"] == 0.45
    assert result["filled_size_usd"] == pytest_approx_or_close(22.5)


def pytest_approx_or_close(expected, rel=1e-6):
    """Light tolerance helper (no pytest dependency required)."""
    class _Approx:
        def __eq__(self, other):
            return abs(other - expected) <= rel * max(abs(expected), abs(other), 1e-12)
        def __repr__(self):
            return f"≈{expected}"
    return _Approx()


def test_nested_order_order_id_is_promoted():
    """order.order_id must be copied to top-level order_id."""
    result = {
        "status": "filled",
        "order": {"order_id": "order-level-id-456"},
    }
    patch._normalize_coinbase_result(result)

    assert result["order_id"] == "order-level-id-456"


def test_top_level_client_order_id_is_promoted():
    """client_order_id already at top level must be promoted when order_id is absent."""
    result = {
        "status": "filled",
        "client_order_id": "client-uuid-xyz",
    }
    patch._normalize_coinbase_result(result)

    assert result["order_id"] == "client-uuid-xyz"


def test_top_level_exchange_order_id_is_promoted():
    """exchange_order_id at top level must be promoted when order_id is absent."""
    result = {
        "status": "filled",
        "exchange_order_id": "exchange-id-999",
    }
    patch._normalize_coinbase_result(result)

    assert result["order_id"] == "exchange-id-999"


def test_raw_success_response_order_id_is_promoted():
    """raw.success_response.order_id must be promoted."""
    result = {
        "status": "filled",
        "raw": {"success_response": {"order_id": "raw-nested-id-789"}},
    }
    patch._normalize_coinbase_result(result)

    assert result["order_id"] == "raw-nested-id-789"


def test_top_level_order_id_is_not_overwritten():
    """An existing top-level order_id must never be replaced."""
    result = {
        "status": "filled",
        "order_id": "original-id",
        "order": {"success_response": {"order_id": "should-not-overwrite"}},
    }
    patch._normalize_coinbase_result(result)

    assert result["order_id"] == "original-id"


# ---------------------------------------------------------------------------
# _normalize_coinbase_result – fill price and notional promotion
# ---------------------------------------------------------------------------

def test_fill_price_promoted_from_success_response():
    result = {
        "status": "filled",
        "order": {"success_response": {"order_id": "id-1", "average_filled_price": "0.3750"}},
    }
    patch._normalize_coinbase_result(result)

    assert result.get("filled_price") == 0.375


def test_filled_size_usd_computed_from_filled_size_times_price():
    result = {
        "status": "filled",
        "order": {
            "success_response": {
                "order_id": "id-2",
                "average_filled_price": "0.50",
                "filled_size": "30.0",
            }
        },
        "filled_size": 30.0,
    }
    patch._normalize_coinbase_result(result)

    usd = result.get("filled_size_usd")
    assert usd is not None and abs(usd - 15.0) < 0.01


def test_filled_size_usd_falls_back_to_size_usd_param():
    """When no fill price is available, size_usd kwarg must be stored as proxy."""
    result = {
        "status": "filled",
        "order": {"success_response": {"order_id": "id-3"}},
    }
    patch._normalize_coinbase_result(result, size_usd=23.0)

    assert result.get("filled_size_usd") == 23.0


# ---------------------------------------------------------------------------
# _looks_confirmed_fill – rejection acceptance criteria
# ---------------------------------------------------------------------------

def test_missing_order_id_is_rejected_after_normalization():
    """A filled result with no discoverable order_id must still fail."""
    result = {"status": "filled"}
    patch._normalize_coinbase_result(result)
    ok, reason = patch._looks_confirmed_fill(result)

    assert ok is False
    assert "pseudo_order_id" in reason or "missing" in reason


def test_rejected_status_fails_even_with_real_order_id():
    """Acceptance criterion 1: rejected responses must never pass as fills."""
    result = {
        "status": "rejected",
        "order_id": "real-id-should-not-matter",
        "filled_price": 1.0,
        "filled_size_usd": 10.0,
    }
    ok, reason = patch._looks_confirmed_fill(result)

    assert ok is False
    assert "reject" in reason


def test_cancelled_status_fails():
    """Acceptance criterion 1: cancelled responses must remain failures."""
    result = {
        "status": "cancelled",
        "order_id": "real-id",
    }
    ok, reason = patch._looks_confirmed_fill(result)

    assert ok is False


def test_cancelled_alternate_spelling_fails():
    result = {
        "status": "canceled",
        "order_id": "real-id",
    }
    ok, reason = patch._looks_confirmed_fill(result)

    assert ok is False


def test_error_status_fails():
    result = {"status": "error", "order_id": "real-id"}
    ok, reason = patch._looks_confirmed_fill(result)
    assert ok is False


def test_open_status_is_unconfirmed():
    result = {"status": "open", "order_id": "real-id"}
    ok, reason = patch._looks_confirmed_fill(result)
    assert ok is False
    assert "unconfirmed" in reason


def test_pending_status_is_unconfirmed():
    result = {"status": "pending", "order_id": "real-id"}
    ok, reason = patch._looks_confirmed_fill(result)
    assert ok is False


def test_unknown_blank_status_is_unconfirmed():
    result = {"order_id": "real-id"}
    ok, reason = patch._looks_confirmed_fill(result)
    assert ok is False


def test_terminal_filled_with_real_order_id_passes():
    """Acceptance criterion 2: filled + real order_id must pass."""
    result = {
        "status": "filled",
        "order_id": "real-uuid-1234",
    }
    ok, reason = patch._looks_confirmed_fill(result)

    assert ok is True
    assert reason == "confirmed_fill"


# ---------------------------------------------------------------------------
# End-to-end: _normalize_coinbase_result + _looks_confirmed_fill integration
# ---------------------------------------------------------------------------

def test_coinbase_nested_fill_passes_gate_end_to_end():
    """
    Acceptance criterion 3: a Coinbase broker response with order_id nested
    in order.success_response must be recognised as a confirmed fill.
    """
    result = {
        "status": "filled",
        "order": {
            "success_response": {
                "order_id": "cb-live-order-ada-usd-20260709",
                "average_filled_price": "0.4512",
                "filled_size": "49.87",
            }
        },
        "filled_size": 49.87,
    }
    patch._normalize_coinbase_result(result, size_usd=22.5)

    ok, reason = patch._looks_confirmed_fill(result)

    assert ok is True, f"Expected confirmed_fill, got: {reason}"
    assert result["order_id"] == "cb-live-order-ada-usd-20260709"
    assert result.get("filled_price", 0) > 0
    assert result.get("filled_size_usd", 0) > 0


def test_coinbase_filled_response_rejected_status_never_passes():
    """Acceptance criterion 1+3: even a nested-id Coinbase response with
    rejected status must not become a confirmed fill."""
    result = {
        "status": "rejected",
        "order": {"success_response": {"order_id": "cb-rejected-order"}},
    }
    patch._normalize_coinbase_result(result)
    ok, reason = patch._looks_confirmed_fill(result)

    assert ok is False
