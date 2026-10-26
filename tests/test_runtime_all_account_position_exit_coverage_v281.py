from types import SimpleNamespace

import pytest

from bot import runtime_all_account_position_exit_coverage_v281_patch as v281


@pytest.fixture(autouse=True)
def _isolate_v281_tracker_coverage_from_newer_v285_broker_probes(monkeypatch):
    """Use only explicit test-fixture snapshots when exercising v281 logic.

    v285's authenticated broker-reader contract is tested separately. These
    legacy unit tests cover the v281 tracker/coverage reconciliation layer.
    Production still calls v285 and fails closed on unavailable proof.
    """

    def snapshot(broker):
        if getattr(broker, "_startup_position_sync_fetch_ok", None) is not True:
            return False, set(), "authoritative_position_fetch_unproven"
        if getattr(broker, "_startup_position_sync_adopted", None) is not True:
            return False, set(), "authoritative_snapshot_not_adopted"
        symbols = {
            v281._normalise_symbol(item)
            for item in broker._startup_position_sync_symbols
        }
        return True, symbols, "test_fixture_authoritative_snapshot"

    monkeypatch.setattr(v281, "_authoritative_snapshot_symbols", snapshot)


class Tracker:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    def get_all_positions(self):
        return list(self.rows)

    def get_position(self, symbol):
        return self.rows.get(symbol)


class Broker:
    def __init__(
        self, *, connected=True, symbols=(), rows=None, fetch_ok=True,
        adopted=True, error="", dust_symbols=(),
    ):
        self.connected = connected
        self._startup_position_sync_fetch_ok = fetch_ok
        self._startup_position_sync_adopted = adopted
        self._startup_position_sync_symbols = tuple(symbols)
        self._startup_position_sync_error = error
        self._startup_position_sync_dust_symbols_v371 = tuple(dust_symbols)
        self.position_tracker = Tracker(rows)


def position(symbol="BTC-USD", qty=0.01, entry=50000.0, *, verified=True, blocked=False):
    return {
        "symbol": symbol,
        "quantity": qty,
        "entry_price": entry,
        "cost_basis_verified": verified,
        "auto_exit_blocked": blocked,
    }


def manager(*, platform=None, all_users=None, users=None, metadata=None, failed=None, missing=None, platform_failed=None):
    return SimpleNamespace(
        _platform_brokers=dict(platform or {}),
        _platform_failed_types=set(platform_failed or ()),
        _all_user_brokers=dict(all_users or {}),
        user_brokers=dict(users or {}),
        _user_metadata=dict(metadata or {}),
        _failed_user_connections=dict(failed or {}),
        _users_without_credentials=dict(missing or {}),
    )


def test_all_accounts_ready_with_authoritative_empty_snapshots():
    kraken = Broker(symbols=(), rows={})
    coinbase = Broker(symbols=(), rows={})
    user = Broker(symbols=(), rows={})
    mgr = manager(
        platform={"kraken": kraken, "coinbase": coinbase},
        all_users={("alice", "kraken"): user},
        metadata={"alice": {"brokers": {"kraken": {"enabled": True}}}},
    )
    result = v281.evaluate(mgr, structural_exit_ready=True)
    assert result["ready"] is True
    assert result["pending"] == {}
    assert result["expected_accounts"] == (
        "platform:coinbase", "platform:kraken", "user:alice:kraken"
    )


def test_disconnected_failed_user_remains_in_coverage_denominator():
    platform = Broker(symbols=(), rows={})
    mgr = manager(
        platform={"kraken": platform},
        metadata={"alice": {"brokers": {"kraken": {"enabled": True}}}},
        failed={("alice", "kraken"): "auth_failed"},
    )
    result = v281.evaluate(mgr, structural_exit_ready=True)
    assert result["ready"] is False
    assert "user:alice:kraken" in result["expected_accounts"]
    assert result["pending"]["user:alice:kraken"] == ("broker_missing",)


def test_explicitly_disabled_user_broker_is_excluded():
    platform = Broker(symbols=(), rows={})
    disabled = Broker(connected=False, fetch_ok=False, adopted=False)
    mgr = manager(
        platform={"kraken": platform},
        all_users={("alice", "alpaca"): disabled},
        metadata={"alice": {"brokers": {"alpaca": {"enabled": False}}}},
    )
    result = v281.evaluate(mgr, structural_exit_ready=True)
    assert result["ready"] is True
    assert result["expected_accounts"] == ("platform:kraken",)


def test_held_position_requires_verified_basis_and_unblocked_exit():
    row = position(verified=False, blocked=True)
    broker = Broker(symbols=("BTC-USD",), rows={"BTC-USD": row})
    mgr = manager(platform={"coinbase": broker})
    result = v281.evaluate(mgr, structural_exit_ready=True)
    assert result["ready"] is False
    reasons = result["pending"]["platform:coinbase"]
    assert "cost_basis_unverified:BTC-USD" in reasons
    assert "auto_exit_blocked:BTC-USD" in reasons
    assert result["positions"][0]["protective_exit_verified"] is False


def test_canonical_dust_is_visible_but_does_not_block_coverage():
    row = position(qty=1e-8, verified=False, blocked=True)
    broker = Broker(
        symbols=("BTC-USD",),
        rows={"BTC-USD": row},
        dust_symbols=("BTC-USD",),
    )
    mgr = manager(platform={"kraken": broker})
    result = v281.evaluate(mgr, structural_exit_ready=True)

    assert result["ready"] is True
    assert result["pending"] == {}
    assert result["positions"][0]["protective_exit_verified"] is False
    assert result["positions"][0]["dust_excluded"] is True
    assert result["positions"][0]["protective_exit_required"] is False
    assert result["positions"][0]["coverage_basis"] == "dust_policy_not_actionable"


def test_unverified_actionable_position_still_fails_closed():
    row = position(qty=0.01, verified=False, blocked=True)
    broker = Broker(symbols=("BTC-USD",), rows={"BTC-USD": row})
    mgr = manager(platform={"kraken": broker})
    result = v281.evaluate(mgr, structural_exit_ready=True)

    assert result["ready"] is False
    assert "cost_basis_unverified:BTC-USD" in result["pending"]["platform:kraken"]
    assert "auto_exit_blocked:BTC-USD" in result["pending"]["platform:kraken"]


def test_authoritative_snapshot_and_tracker_must_match_exactly():
    broker = Broker(
        symbols=("BTC-USD",),
        rows={
            "BTC-USD": position("BTC-USD"),
            "ETH-USD": position("ETH-USD", qty=0.2, entry=3000.0),
        },
    )
    mgr = manager(platform={"coinbase": broker})
    result = v281.evaluate(mgr, structural_exit_ready=True)
    assert result["ready"] is False
    assert "stale_tracker_not_in_authoritative_snapshot:ETH-USD" in result["pending"]["platform:coinbase"]


def test_authoritative_symbol_missing_from_tracker_fails_closed():
    broker = Broker(symbols=("BTC-USD",), rows={})
    mgr = manager(platform={"coinbase": broker})
    result = v281.evaluate(mgr, structural_exit_ready=True)
    assert result["ready"] is False
    assert result["pending"]["platform:coinbase"] == (
        "authoritative_snapshot_missing_tracker_position:BTC-USD",
    )


def test_verified_held_position_is_certified_when_v265_ready():
    broker = Broker(
        symbols=("BTC-USD",),
        rows={"BTC-USD": position()},
    )
    mgr = manager(platform={"coinbase": broker})
    result = v281.evaluate(mgr, structural_exit_ready=True)
    assert result["ready"] is True
    assert result["pending"] == {}
    assert result["positions"][0]["protective_exit_verified"] is True


def test_structural_exit_authority_is_required_without_mutating_platform_readiness():
    broker = Broker(symbols=(), rows={})
    mgr = manager(platform={"kraken": broker})
    result = v281.evaluate(mgr, structural_exit_ready=False)
    assert result["ready"] is False
    assert result["pending"]["__protective_exit__"] == (
        "protective_exit_authority_v265_unready",
    )


def test_dust_exemption_never_claims_verified_protection_even_with_other_ready_flags():
    broker = Broker(
        symbols=("BABY-USD",),
        rows={"BABY-USD": position("BABY-USD", qty=0.00142, entry=0.01217,
                                   verified=True, blocked=False)},
        dust_symbols=("BABY-USD",),
    )
    result = v281.evaluate(manager(platform={"kraken": broker}), structural_exit_ready=True)

    assert result["ready"] is True  # Actionable-position policy; NOT all holdings protected.
    assert result["dust_exempt_not_protected_count"] == 1
    row = result["positions"][0]
    assert row["dust_excluded"] is True
    assert row["protective_exit_required"] is False
    assert row["protective_exit_verified"] is False
    assert row["coverage_basis"] == "dust_policy_not_actionable"


def test_dust_exemption_audit_log_explicitly_disclaims_protection(caplog, monkeypatch):
    broker = Broker(
        symbols=("BABY-USD",),
        rows={"BABY-USD": position("BABY-USD", qty=0.00142, verified=False,
                                   blocked=True)},
        dust_symbols=("BABY-USD",),
    )
    monkeypatch.setattr(v281, "_LAST_SIGNATURE", "")
    with caplog.at_level("CRITICAL", logger="nija.runtime_all_account_position_exit_coverage_v281"):
        result = v281.audit_once(manager(platform={"kraken": broker}),
                                 structural_exit_ready=True)

    assert result["dust_exempt_not_protected_count"] == 1
    assert "coverage_scope=actionable_positions_only" in caplog.text
    assert "dust_exempt_not_protected_count=1" in caplog.text
    assert "independent_broker_exit_proof_performed=false" in caplog.text
    assert "execution_authorization_provided=false" in caplog.text
    assert result["positions"][0]["cost_basis_verified"] is False
    assert result["positions"][0]["auto_exit_blocked"] is True
    assert result["positions"][0]["protective_exit_verified"] is False


def test_dust_exemption_protection_fields_participate_in_state_signature():
    original = {
        "ready": True,
        "expected_accounts": ("platform:kraken",),
        "pending": {},
        "positions": ({
            "account": "platform:kraken",
            "symbol": "BABY-USD",
            "quantity": 0.00142,
            "entry_price": 0.01217,
            "protective_exit_verified": False,
            "cost_basis_verified": False,
            "auto_exit_blocked": True,
            "dust_excluded": True,
            "protective_exit_required": False,
        },),
        "structural_exit_ready": True,
    }
    changed = dict(original)
    changed["positions"] = (dict(original["positions"][0], dust_excluded=False),)
    assert v281._state_signature(original) != v281._state_signature(changed)

    changed["positions"] = (dict(original["positions"][0], cost_basis_verified=True),)
    assert v281._state_signature(original) != v281._state_signature(changed)


def test_platform_scope_diagnostic_isolates_disconnected_member_without_granting_authority():
    platform = Broker(symbols=(), rows={})
    disconnected = Broker(connected=False, fetch_ok=False, adopted=False)
    mgr = manager(
        platform={"kraken": platform},
        all_users={("daivon", "kraken"): disconnected},
        metadata={"daivon": {"brokers": {"kraken": True}}},
    )
    full = v281.evaluate(mgr, structural_exit_ready=True)
    assert full["ready"] is False
    assert "user:daivon:kraken" in full["pending"]
    scoped = v281.platform_scope_diagnostics(full)
    assert scoped["platform_ready"] is True
    assert scoped["platform_expected"] == ("platform:kraken",)
    assert scoped["platform_pending"] == {}
    assert "user:daivon:kraken" in scoped["user_pending"]
    assert scoped["all_account_ready"] is False
    assert scoped["diagnostic_only"] is True
    assert scoped["authorizes_orders"] is False


def test_platform_scope_diagnostic_preserves_platform_disconnect_blocker():
    mgr = manager(platform={"kraken": Broker(connected=False)})
    full = v281.evaluate(mgr, structural_exit_ready=True)
    scoped = v281.platform_scope_diagnostics(full)
    assert scoped["platform_ready"] is False
    assert scoped["platform_pending"]["platform:kraken"] == ("disconnected",)


def test_platform_scope_diagnostic_preserves_actionable_exit_failure():
    broker = Broker(
        symbols=("BTC-USD",),
        rows={"BTC-USD": position(verified=False, blocked=True)},
    )
    full = v281.evaluate(manager(platform={"okx": broker}), structural_exit_ready=True)
    scoped = v281.platform_scope_diagnostics(full)
    assert scoped["platform_ready"] is False
    assert "platform:okx" in scoped["platform_pending"]
    assert scoped["authorizes_orders"] is False


def test_platform_scope_diagnostic_rejects_missing_global_or_malformed_proof():
    platform = Broker(symbols=(), rows={})
    full = v281.evaluate(manager(platform={"kraken": platform}), structural_exit_ready=False)
    scoped = v281.platform_scope_diagnostics(full)
    assert scoped["platform_ready"] is False
    assert "__protective_exit__" in scoped["platform_pending"]
    for bad in (None, {}, {"ready": True, "expected_accounts": ("platform:kraken",), "pending": {}}):
        rejected = v281.platform_scope_diagnostics(bad)
        assert rejected["platform_ready"] is False
        assert rejected["authorizes_orders"] is False


def test_platform_scope_diagnostic_rejects_unverified_position_row():
    result = {
        "ready": True,
        "expected_accounts": ("platform:kraken",),
        "pending": {},
        "positions": ({"account": "platform:kraken", "protective_exit_required": True,
                       "protective_exit_verified": False},),
        "structural_exit_ready": True,
    }
    scoped = v281.platform_scope_diagnostics(result)
    assert scoped["platform_ready"] is False
    assert scoped["platform_pending"]["platform:kraken"] == (
        "actionable_position_protection_unverified",
    )
