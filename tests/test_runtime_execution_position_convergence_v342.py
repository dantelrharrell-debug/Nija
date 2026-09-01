from __future__ import annotations

from types import ModuleType, SimpleNamespace

from bot import runtime_execution_position_convergence_v342_patch as v342


def test_bad_eth_cost_basis_is_blocked():
    row = {
        "symbol": "ETH-USD",
        "quantity": 0.00629411,
        "entry_price": 33550.21684731,
        "current_price": 2474.75,
        "cost_basis_verified": True,
    }
    sane, reason, entry, market = v342._cost_basis_sanity(row)
    assert sane is False
    assert "entry_market_ratio=" in reason
    assert entry == row["entry_price"]
    assert market == row["current_price"]


def test_normal_cost_basis_is_accepted():
    row = {
        "symbol": "ETH-USD",
        "quantity": 0.1,
        "entry_price": 2500.0,
        "current_price": 2474.75,
        "cost_basis_verified": True,
    }
    sane, reason, _, _ = v342._cost_basis_sanity(row)
    assert sane is True
    assert reason == "entry_market_sane"


def test_explicit_unverified_cost_basis_is_blocked():
    sane, reason, _, _ = v342._cost_basis_sanity({
        "symbol": "BTC-USD",
        "quantity": 0.01,
        "entry_price": 70000.0,
        "current_price": 71000.0,
        "cost_basis_verified": False,
    })
    assert sane is False
    assert reason == "cost_basis_explicitly_unverified"


def test_profit_target_synthesis_blocks_bad_basis_and_preserves_existing_target():
    module = ModuleType("runtime_all_account_profit_targets_v239_patch")

    def original(row):
        result = dict(row)
        result.setdefault("take_profit_1", float(result["entry_price"]) * 1.005)
        return result

    module._with_profit_targets = original
    assert v342._patch_profit_target_sanity(module) is True

    bad = module._with_profit_targets({
        "symbol": "ETH-USD",
        "quantity": 0.00629411,
        "entry_price": 33550.21684731,
        "current_price": 2474.75,
        "cost_basis_verified": True,
    })
    assert "take_profit_1" not in bad

    good = module._with_profit_targets({
        "symbol": "ETH-USD",
        "quantity": 0.1,
        "entry_price": 2500.0,
        "current_price": 2474.75,
        "cost_basis_verified": True,
    })
    assert good["take_profit_1"] == 2500.0 * 1.005

    explicit = module._with_profit_targets({
        "symbol": "ETH-USD",
        "quantity": 0.1,
        "entry_price": 33550.0,
        "current_price": 2474.75,
        "take_profit_1": 2600.0,
    })
    assert explicit["take_profit_1"] == 2600.0


def test_kraken_microcap_live_flight_budget_is_reduced_from_three_intervals(monkeypatch):
    module = ModuleType("runtime_kraken_position_flight_recovery_v287_patch")
    module._monitoring_interval_s = lambda broker: 60.0
    module._flight_hard_age_s = lambda flight: 180.0
    monkeypatch.delenv("NIJA_KRAKEN_POSITION_PROGRESS_MAX_AGE_S", raising=False)
    monkeypatch.delenv("NIJA_KRAKEN_POSITION_PROGRESS_GRACE_S", raising=False)

    assert v342._patch_kraken_flight_deadline(module) is True
    budget = module._flight_hard_age_s({"broker": object()})
    assert budget == 90.0


def test_coinbase_position_context_forces_single_inner_attempt_only():
    module = ModuleType("bot.broker_manager")
    namespace = module.__dict__
    exec(
        """
class CoinbaseBroker:
    def __init__(self):
        self.calls = []
    def _api_call_with_retry(self, api_func, *args, max_retries=3, base_delay=5.0, **kwargs):
        self.calls.append((max_retries, base_delay, dict(kwargs)))
        return 'ok'
    def get_positions(self):
        return self._api_call_with_retry(lambda: None, max_retries=3, base_delay=5.0)
""",
        namespace,
    )
    assert v342._patch_coinbase_retry_budget(module) is True
    broker = module.CoinbaseBroker()
    assert broker.get_positions() == "ok"
    assert broker.calls[-1][0] == 1
    assert broker.calls[-1][1] <= 1.0

    broker._api_call_with_retry(lambda: None, max_retries=3, base_delay=5.0)
    assert broker.calls[-1][0] == 3
    assert broker.calls[-1][1] == 5.0


def test_v320_idempotency_guard_walks_wrapped_chain():
    v320 = ModuleType("runtime_platform_position_sync_isolation_v320_patch")
    v320._REFRESH_PATCH_ATTR = "_refresh_v323"
    calls = {"count": 0}

    def legacy(v285):
        calls["count"] += 1
        return True

    v320._patch_v285_platform_refresh = legacy
    assert v342._patch_v320_idempotency(v320) is True

    def inner(manager):
        return []
    setattr(inner, "_refresh_v323", True)

    def outer(manager):
        return inner(manager)
    outer.__wrapped__ = inner

    fake_v285 = SimpleNamespace(_platform_candidates=outer)
    assert v320._patch_v285_platform_refresh(fake_v285) is True
    assert calls["count"] == 0
