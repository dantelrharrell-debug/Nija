from __future__ import annotations

import importlib.util
import os
import sys
import types
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BOT_DIR = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, BOT_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


exit_runtime = load_module(
    "kraken_all_account_exit_runtime_under_test",
    "kraken_all_account_exit_runtime_patch.py",
)
safety = load_module(
    "kraken_exit_safety_convergence_under_test",
    "kraken_exit_safety_convergence_patch.py",
)


class KrakenBroker:
    NAME = "Kraken"

    def __init__(self, account="platform", private_ok=True):
        self.account_identifier = account
        self.connected = True
        self.private_ok = private_ok
        self.private_calls = []
        self.public_calls = []

    def _kraken_api_call(self, method, params=None):
        self.private_calls.append((method, dict(params or {})))
        if method == "TradeBalance":
            if not self.private_ok:
                return {"error": ["EAPI:Invalid key"], "result": {}}
            return {
                "error": [],
                "result": {
                    "eb": "100.0",
                    "e": "100.0",
                    "tb": "90.0",
                    "mf": "90.0",
                    "m": "0.0",
                },
            }
        return {"error": [], "result": {}}

    def query_public(self, method, params=None):
        self.public_calls.append((method, dict(params or {})))
        pair = str((params or {}).get("pair") or "")
        if method == "AssetPairs" and pair == "AIREUR":
            return {"error": [], "result": {"AIREUR": {"altname": "AIREUR"}}}
        if method == "AssetPairs":
            return {"error": ["EQuery:Unknown asset pair"], "result": {}}
        if method == "Ticker" and pair == "AIREUR":
            return {"error": [], "result": {"AIREUR": {"c": ["0.011", "1"]}}}
        return {"error": ["not mocked"], "result": {}}


class TestPrivateConnectionHealth:
    def setup_method(self):
        exit_runtime._PRIVATE_HEALTH.clear()

    def test_private_probe_is_per_adapter(self):
        platform = KrakenBroker("platform", private_ok=True)
        tania = KrakenBroker("USER:tania_gilbert", private_ok=False)

        assert exit_runtime._private_ready(platform, "platform:kraken", force=True)[0] is True
        ready, reason = exit_runtime._private_ready(tania, "user:tania_gilbert:kraken", force=True)
        assert ready is False
        assert "Invalid key" in reason
        assert len(platform.private_calls) == 1
        assert len(tania.private_calls) == 1

    def test_alive_thread_requires_private_readiness(self):
        module = types.ModuleType("account_exit_management_recovery_patch")
        module._connect = lambda broker, identity: broker.connected
        module._normal_thread_alive = lambda *args: True
        module._adopt_and_manage = lambda trader, identity, broker: (0, 0)
        module._retry_all_accounts = lambda trader: None
        assert exit_runtime._patch_recovery_module(module)

        broker = KrakenBroker("USER:tania_gilbert", private_ok=False)
        alive = module._normal_thread_alive(
            SimpleNamespace(), "user", "tania_gilbert",
            SimpleNamespace(value="kraken"), broker,
        )
        assert alive is False


class TestPairAndExitDecisions:
    def setup_method(self):
        exit_runtime._PAIR_CACHE.clear()
        exit_runtime._EXIT_STATE.clear()

    def test_air_resolves_to_an_available_kraken_quote_pair(self):
        broker = KrakenBroker("USER:tania_gilbert")
        assert exit_runtime._resolve_pair(broker, "AIR-USD") == "AIREUR"
        attempted = [params["pair"] for method, params in broker.public_calls if method == "AssetPairs"]
        assert "AIRUSD" in attempted
        assert "AIRUSDT" in attempted
        assert "AIREUR" in attempted

    def test_net_profit_target_is_preferred(self):
        position = {
            "symbol": "SOL-USD",
            "side": "long",
            "entry_price": 100.0,
            "quantity": 1.0,
            "first_entry_time": datetime.now(timezone.utc).isoformat(),
        }
        with patch.dict(
            os.environ,
            {
                "NIJA_KRAKEN_EXIT_ROUND_TRIP_COST_PCT": "0.008",
                "NIJA_KRAKEN_EXIT_NET_PROFIT_TARGET_PCT": "0.004",
            },
            clear=False,
        ):
            reason, breakeven, target = exit_runtime._exit_reason(
                position, 101.25, "platform:kraken", "SOL-USD"
            )
        assert reason == "net_profit_target"
        assert round(breakeven, 2) == 100.80
        assert round(target, 2) == 101.20

    def test_fee_adjusted_break_even_after_max_hold(self):
        position = {
            "symbol": "SOL-USD",
            "side": "long",
            "entry_price": 100.0,
            "quantity": 1.0,
            "first_entry_time": (
                datetime.now(timezone.utc) - timedelta(minutes=61)
            ).isoformat(),
        }
        with patch.dict(
            os.environ,
            {
                "NIJA_KRAKEN_EXIT_ROUND_TRIP_COST_PCT": "0.008",
                "NIJA_KRAKEN_EXIT_NET_PROFIT_TARGET_PCT": "0.004",
                "NIJA_KRAKEN_BREAK_EVEN_MAX_HOLD_MINUTES": "60",
                "NIJA_KRAKEN_BREAK_EVEN_EXIT_ENABLED": "true",
            },
            clear=False,
        ):
            reason, _, _ = exit_runtime._exit_reason(
                position, 100.90, "platform:kraken", "SOL-USD"
            )
        assert reason == "fee_adjusted_break_even"

    def test_stop_loss_remains_available_when_market_never_recovers(self):
        position = {
            "symbol": "SOL-USD",
            "side": "long",
            "entry_price": 100.0,
            "quantity": 1.0,
            "stop_loss": 95.0,
        }
        reason, _, _ = exit_runtime._exit_reason(
            position, 94.0, "platform:kraken", "SOL-USD"
        )
        assert reason == "emergency_stop_loss"


class TestExplicitExitContext:
    def test_supervisor_identity_is_normalized_for_pipeline_and_ledger(self):
        captured = {}

        def submit_market_order_via_pipeline(**kwargs):
            captured.update(kwargs)
            return {"status": "filled", "order_id": "1"}

        fake_submitter = types.ModuleType("bot.pipeline_order_submitter")
        fake_submitter.submit_market_order_via_pipeline = submit_market_order_via_pipeline
        fake_bot = types.ModuleType("bot")
        fake_bot.__path__ = []
        fake_bot.pipeline_order_submitter = fake_submitter

        module = types.ModuleType("bot.kraken_all_account_exit_runtime_patch")
        module._submit_exit = lambda *args, **kwargs: {"status": "error"}
        assert safety._patch_all_account_exit(module)

        with patch.dict(
            sys.modules,
            {"bot": fake_bot, "bot.pipeline_order_submitter": fake_submitter},
            clear=False,
        ):
            result = module._submit_exit(
                KrakenBroker("USER:tania_gilbert"),
                "user:tania_gilbert:kraken",
                "AIREUR",
                100.0,
                "fee_adjusted_break_even",
            )

        assert result["status"] == "filled"
        assert captured["account_id_override"] == "tania_gilbert"
        assert captured["intent_type"] == "exit"
        assert captured["position_effect"] == "close"
        assert captured["metadata_override"]["closing_position"] is True

    def test_platform_and_user_identity_normalization(self):
        assert safety._canonical_account_id("platform:kraken") == "platform"
        assert safety._canonical_account_id("user:daivon_frazier:kraken") == "daivon_frazier"
        assert safety._canonical_account_id("USER:tania_gilbert") == "tania_gilbert"


class TestExitOnlyCycleScope:
    def test_recovery_user_mode_cannot_be_auto_promoted_to_entries(self):
        truth_module = types.ModuleType("bot.trade_cycle_convergence_repair_patch")
        truth_module._truthy = lambda name, default=False: True
        recovery = types.ModuleType("account_exit_management_recovery_patch")
        recovery._adopt_and_manage = lambda trader, identity, broker: truth_module._truthy(
            "NIJA_INDEPENDENT_USER_TRADING", True
        )

        assert safety._patch_trade_cycle_truth(truth_module)
        assert safety._patch_recovery_scope(recovery)
        assert truth_module._truthy("NIJA_INDEPENDENT_USER_TRADING", True) is True
        assert recovery._adopt_and_manage(None, "user:daivon:kraken", None) is False
        assert truth_module._truthy("NIJA_INDEPENDENT_USER_TRADING", True) is True


class TestMarginRiskReduction:
    def test_critical_margin_allows_reduce_only_but_not_new_entry(self):
        class KrakenMarginEngine:
            account_id = "tania_gilbert"

            def is_margin_trade_allowed(self, *, is_reducing=False, adapter=None):
                return False, "critical_margin:critical_margin_level:85.0%"

        module = types.ModuleType("bot.kraken_margin_engine")
        module.KrakenMarginEngine = KrakenMarginEngine
        assert safety._patch_margin_engine(module)
        engine = KrakenMarginEngine()

        assert engine.is_margin_trade_allowed(is_reducing=False)[0] is False
        allowed, reason = engine.is_margin_trade_allowed(is_reducing=True)
        assert allowed is True
        assert reason.startswith("risk_reducing_exit:")

    def test_permission_failure_is_not_bypassed(self):
        class KrakenMarginEngine:
            account_id = "daivon_frazier"

            def is_margin_trade_allowed(self, *, is_reducing=False, adapter=None):
                return False, "permission_denied"

        module = types.ModuleType("bot.kraken_margin_engine.permission")
        module.KrakenMarginEngine = KrakenMarginEngine
        assert safety._patch_margin_engine(module)
        assert KrakenMarginEngine().is_margin_trade_allowed(is_reducing=True) == (
            False, "permission_denied"
        )


class TestPipelineExitGateSplit:
    def test_exit_bypasses_entry_only_gates_and_restores_them(self):
        sentinel = object()

        class ExecutionPipeline:
            def __init__(self):
                self._pre_trade_risk_engine = sentinel
                self._allocation_clamp = sentinel
                self._execution_observer = sentinel
                self._throttler = sentinel
                self._downstream_guard = sentinel

            def _gate_broker_capabilities(self, request, t_start):
                return "blocked_as_short"

            def execute(self, request):
                return tuple(
                    getattr(self, name)
                    for name in (
                        "_pre_trade_risk_engine", "_allocation_clamp",
                        "_execution_observer", "_throttler", "_downstream_guard",
                    )
                )

        module = types.ModuleType("bot.execution_pipeline")
        module.ExecutionPipeline = ExecutionPipeline
        assert exit_runtime._patch_execution_pipeline(module)
        pipeline = ExecutionPipeline()
        exit_request = SimpleNamespace(
            intent_type="exit", position_effect="close", metadata={},
            account_id="tania_gilbert", symbol="AIR-EUR", side="sell",
        )
        entry_request = SimpleNamespace(
            intent_type="entry", position_effect=None, metadata={},
            account_id="tania_gilbert", symbol="AIR-EUR", side="sell",
        )

        assert pipeline._gate_broker_capabilities(exit_request, 0.0) is None
        assert pipeline._gate_broker_capabilities(entry_request, 0.0) == "blocked_as_short"
        assert pipeline.execute(exit_request) == (None, None, None, None, None)
        assert pipeline.execute(entry_request) == (sentinel, sentinel, sentinel, sentinel, sentinel)
        assert pipeline._pre_trade_risk_engine is sentinel
        assert pipeline._throttler is sentinel


class TestLegacyMonitorIsolation:
    def test_only_kraken_global_scan_is_redirected(self):
        original_start = lambda engine: "started"

        def disabled_start(engine):
            return None

        disabled_start._nija_account_local_disabled_v1 = True
        disabled_start.__wrapped__ = original_start

        module = types.ModuleType("bot.auto_exit_sl_tp_runtime_patch")
        module._start_monitor = disabled_start
        module._scan_once = lambda engine: 7
        assert safety._patch_legacy_auto_exit(module)

        assert module._start_monitor(None) == "started"
        assert module._scan_once(SimpleNamespace(broker_client=KrakenBroker())) == 0
        assert module._scan_once(
            SimpleNamespace(broker_client=SimpleNamespace(NAME="Coinbase"))
        ) == 7
