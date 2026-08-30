from __future__ import annotations

from types import SimpleNamespace

from bot import runtime_dust_position_policy_convergence_v296_patch as v296


class _Tracker:
    def __init__(self, rows):
        self.rows = rows

    def get_position(self, symbol):
        return self.rows.get(symbol)


class _Broker:
    def __init__(self, tracker):
        self.position_tracker = tracker
        self._startup_position_sync_adopted = False
        self._startup_position_sync_symbols = ()
        self.account_identifier = "PLATFORM"


def _dust_row():
    return {
        "quantity": 1e-8,
        "entry_price": 0.0,
        "cost_basis_verified": False,
        "auto_exit_blocked": True,
        "classification": "DUST",
        "exclude_from_reconciliation": True,
        "exclude_from_auto_exit": True,
        "exclude_from_strategy": True,
        "exclude_from_position_limit": True,
    }


def test_policy_dust_requires_all_existing_policy_flags():
    row = _dust_row()
    assert v296._is_policy_dust(row) is True
    for key in (
        "exclude_from_reconciliation",
        "exclude_from_auto_exit",
        "exclude_from_strategy",
        "exclude_from_position_limit",
    ):
        modified = dict(row)
        modified[key] = False
        assert v296._is_policy_dust(modified) is False


def test_dust_can_complete_quantity_adoption_without_fabricating_cost_basis():
    tracker = _Tracker({
        "BTC-USD": {
            "quantity": 0.001,
            "entry_price": 60000.0,
            "cost_basis_verified": True,
        },
        "ETH-USD": _dust_row(),
    })
    broker = _Broker(tracker)
    broker._startup_position_sync_symbols = ("BTC-USD",)
    authoritative = [
        {"symbol": "BTC-USD", "quantity": 0.001},
        {"symbol": "ETH-USD", "quantity": 1e-8},
    ]

    assert v296._apply_dust_adoption(broker, authoritative, "platform:test") is True
    assert broker._startup_position_sync_adopted is True
    assert broker._startup_position_sync_symbols == ("BTC-USD", "ETH-USD")
    assert broker._startup_position_sync_dust_symbols_v296 == ("ETH-USD",)
    # Most important: the tracker truth is untouched.
    assert tracker.rows["ETH-USD"]["cost_basis_verified"] is False
    assert tracker.rows["ETH-USD"]["entry_price"] == 0.0
    assert tracker.rows["ETH-USD"]["auto_exit_blocked"] is True


def test_non_dust_unverified_position_stays_fail_closed():
    tracker = _Tracker({
        "BTC-USD": {
            "quantity": 0.001,
            "entry_price": 0.0,
            "cost_basis_verified": False,
            "classification": "ACTIVE",
            "exclude_from_reconciliation": False,
            "exclude_from_auto_exit": False,
            "exclude_from_strategy": False,
            "exclude_from_position_limit": False,
        }
    })
    broker = _Broker(tracker)
    authoritative = [{"symbol": "BTC-USD", "quantity": 0.001}]

    assert v296._apply_dust_adoption(broker, authoritative, "platform:test") is False
    assert broker._startup_position_sync_adopted is False


def test_invalid_authoritative_row_never_becomes_dust_success():
    broker = _Broker(_Tracker({"BTC-USD": _dust_row()}))
    rows = [
        {"symbol": "BTC-USD", "quantity": 1e-8},
        {"symbol": "", "quantity": 1e-8},
    ]
    assert v296._apply_dust_adoption(broker, rows, "platform:test") is False
    assert broker._startup_position_sync_adopted is False


def test_exit_audit_removes_only_dust_not_applicable_requirements():
    tracker = _Tracker({"ETH-USD": _dust_row()})
    broker = _Broker(tracker)
    reasons = [
        "cost_basis_unverified:ETH-USD",
        "entry_price_unverified:ETH-USD",
        "auto_exit_blocked:ETH-USD",
        "stale_tracker_not_in_authoritative_snapshot:BTC-USD",
    ]
    positions = [{
        "symbol": "ETH-USD",
        "quantity": 1e-8,
        "entry_price": 0.0,
        "cost_basis_verified": False,
        "auto_exit_blocked": True,
        "protective_exit_verified": False,
    }]

    filtered, enriched, dust = v296._strip_dust_protection_reasons(
        broker, reasons, positions
    )

    assert filtered == ["stale_tracker_not_in_authoritative_snapshot:BTC-USD"]
    assert dust == ("ETH-USD",)
    assert enriched[0]["dust_excluded"] is True
    assert enriched[0]["protective_exit_required"] is False
    assert enriched[0]["protective_exit_verified"] is False
    assert enriched[0]["coverage_basis"] == "dust_policy_not_actionable"


def test_active_unverified_position_keeps_all_exit_blockers():
    tracker = _Tracker({
        "BTC-USD": {
            "classification": "ACTIVE",
            "exclude_from_reconciliation": False,
            "exclude_from_auto_exit": False,
            "exclude_from_strategy": False,
            "exclude_from_position_limit": False,
        }
    })
    broker = _Broker(tracker)
    reasons = [
        "cost_basis_unverified:BTC-USD",
        "entry_price_unverified:BTC-USD",
        "auto_exit_blocked:BTC-USD",
    ]
    positions = [{"symbol": "BTC-USD", "protective_exit_verified": False}]

    filtered, enriched, dust = v296._strip_dust_protection_reasons(
        broker, reasons, positions
    )

    assert filtered == reasons
    assert dust == ()
    assert "protective_exit_required" not in enriched[0]


def test_capture_proxy_uses_same_broker_call_and_does_not_copy_truth():
    rows = [{"symbol": "ETH-USD", "quantity": 1e-8}]

    class _CaptureBroker(_Broker):
        def get_positions(self):
            return rows

    broker = _CaptureBroker(_Tracker({}))
    proxy = v296._CapturePositionsProxy(broker)
    assert proxy.get_positions() is rows
    assert proxy.captured_rows() is rows
