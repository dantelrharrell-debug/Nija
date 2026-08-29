from types import SimpleNamespace

from bot import runtime_all_account_position_exit_coverage_v281_patch as v281


class Tracker:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    def get_all_positions(self):
        return list(self.rows)

    def get_position(self, symbol):
        return self.rows.get(symbol)


class Broker:
    def __init__(self, *, connected=True, symbols=(), rows=None, fetch_ok=True, adopted=True, error=""):
        self.connected = connected
        self._startup_position_sync_fetch_ok = fetch_ok
        self._startup_position_sync_adopted = adopted
        self._startup_position_sync_symbols = tuple(symbols)
        self._startup_position_sync_error = error
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
