import importlib.util
import os
import sys
import threading
import types
from pathlib import Path

PATCH_PATH = Path(__file__).parents[1] / "global_drawdown_capital_authority_v91_patch.py"


def _load_patch(name="v91_under_test"):
    spec = importlib.util.spec_from_file_location(name, PATCH_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeAuthority:
    def __init__(self, equity=467.0, hydrated=True, complete=True, fresh=True):
        self.equity = equity
        self.is_hydrated = hydrated
        self.complete = complete
        self.fresh = fresh

    def is_brokers_complete(self):
        return self.complete

    def is_fresh(self, ttl_s=60):
        return self.fresh

    def get_real_capital(self):
        return self.equity


def _install_capital_module(monkeypatch, authority):
    mod = types.ModuleType("bot.capital_authority")
    mod.get_capital_authority = lambda: authority
    monkeypatch.setitem(sys.modules, "bot.capital_authority", mod)


def _install_fake_drawdown_module(monkeypatch):
    bot = sys.modules.get("bot")
    if bot is None:
        bot = types.ModuleType("bot")
        bot.__path__ = []
        monkeypatch.setitem(sys.modules, "bot", bot)

    mod = types.ModuleType("bot.drawdown_risk_controller")

    class Controller:
        def __init__(self):
            self._lock = threading.Lock()
            self._peak_balance = 0.0
            self.seen = []

        def _layer_drawdown(self, balance):
            self.seen.append(balance)
            return "CLEAR", 1.0, False, ""

    mod.DrawdownRiskController = Controller
    monkeypatch.setitem(sys.modules, "bot.drawdown_risk_controller", mod)
    setattr(bot, "drawdown_risk_controller", mod)
    return Controller


def test_aggregate_guard_never_feeds_broker_local_balance(monkeypatch):
    patch = _load_patch("v91_aggregate")
    monkeypatch.setenv("NIJA_V91_FORCE_PRODUCTION", "1")
    authority = FakeAuthority(equity=466.94)
    _install_capital_module(monkeypatch, authority)
    Controller = _install_fake_drawdown_module(monkeypatch)

    assert patch._patch_drawdown_controller() is True
    ctrl = Controller()
    assert ctrl._layer_drawdown(144.96)[2] is False
    assert ctrl._layer_drawdown(95.12)[2] is False
    assert ctrl.seen == [466.94, 466.94]
    assert ctrl._peak_balance == 466.94


def test_stale_aggregate_blocks_without_delegating(monkeypatch):
    patch = _load_patch("v91_stale")
    monkeypatch.setenv("NIJA_V91_FORCE_PRODUCTION", "1")
    _install_capital_module(monkeypatch, FakeAuthority(fresh=False))
    Controller = _install_fake_drawdown_module(monkeypatch)

    assert patch._patch_drawdown_controller() is True
    ctrl = Controller()
    result = ctrl._layer_drawdown(95.12)
    assert result[0] == "HALT"
    assert result[2] is True
    assert "aggregate capital proof unavailable" in result[3]
    assert ctrl.seen == []


def test_non_production_preserves_original_behavior(monkeypatch):
    patch = _load_patch("v91_nonprod")
    monkeypatch.delenv("NIJA_V91_FORCE_PRODUCTION", raising=False)
    for key in (
        "RAILWAY_GIT_COMMIT_SHA",
        "GIT_COMMIT_SHA",
        "SOURCE_VERSION",
        "RENDER_GIT_COMMIT",
        "HEROKU_SLUG_COMMIT",
        "LIVE_CAPITAL_VERIFIED",
    ):
        monkeypatch.delenv(key, raising=False)
    Controller = _install_fake_drawdown_module(monkeypatch)

    assert patch._patch_drawdown_controller() is True
    ctrl = Controller()
    ctrl._layer_drawdown(95.12)
    assert ctrl.seen == [95.12]


def test_exact_incident_signature_required(monkeypatch):
    patch = _load_patch("v91_signature")

    class KS:
        _activation_history = [
            {
                "source": "GlobalDrawdownCircuitBreaker",
                "reason": "GlobalDrawdownCircuitBreaker: HALT level reached (drawdown=34.39%, equity=$95.12)",
                "timestamp": "2026-08-09T13:28:29.115000+00:00",
            },
            {
                "source": "FILE_SYSTEM",
                "reason": "Kill switch file detected",
                "timestamp": "2026-08-14T20:00:00+00:00",
            },
        ]

    record = patch._last_non_file_activation(KS())
    assert patch._matches_known_false_incident(record) is True
    bad = dict(record)
    bad["reason"] = "GlobalDrawdownCircuitBreaker: HALT level reached (drawdown=25.00%, equity=$95.12)"
    assert patch._matches_known_false_incident(bad) is False


def test_recovery_refreshes_then_deactivates_canonically(monkeypatch):
    patch = _load_patch("v91_recovery")
    monkeypatch.setenv("NIJA_V91_FORCE_PRODUCTION", "1")
    patch._PATCHED = True
    patch._RECOVERY_LAST_ATTEMPT = -100.0
    authority = FakeAuthority(equity=466.94, fresh=False)
    _install_capital_module(monkeypatch, authority)

    bot = sys.modules.get("bot")
    if bot is None:
        bot = types.ModuleType("bot")
        bot.__path__ = []
        monkeypatch.setitem(sys.modules, "bot", bot)

    class KS:
        def __init__(self):
            self.active = True
            self.deactivate_reasons = []
            self._activation_history = [
                {
                    "source": "GlobalDrawdownCircuitBreaker",
                    "reason": "GlobalDrawdownCircuitBreaker: HALT level reached (drawdown=34.39%, equity=$95.12)",
                    "timestamp": "2026-08-09T13:28:29.115000+00:00",
                },
                {
                    "source": "FILE_SYSTEM",
                    "reason": "Kill switch file detected",
                    "timestamp": "2026-08-14T20:00:00+00:00",
                },
            ]

        def is_active(self):
            return self.active

        def deactivate(self, reason=""):
            self.deactivate_reasons.append(reason)
            self.active = False

    ks = KS()
    ks_mod = types.ModuleType("bot.kill_switch")
    ks_mod.get_kill_switch = lambda: ks
    monkeypatch.setitem(sys.modules, "bot.kill_switch", ks_mod)

    class Manager:
        def all_brokers_fully_ready(self):
            return True

        def is_ready_for_balance_fetch(self):
            return True, ""

        def refresh_capital_authority(self, trigger="manual"):
            authority.fresh = True
            return {"ready": 1.0, "total_capital": authority.equity, "valid_brokers": 3.0}

    manager_mod = types.ModuleType("bot.multi_account_broker_manager")
    manager_mod.get_broker_manager = lambda: Manager()
    monkeypatch.setitem(sys.modules, "bot.multi_account_broker_manager", manager_mod)

    class Breaker:
        def __init__(self):
            self.baselines = []

        def initialise(self, starting_equity):
            self.baselines.append(starting_equity)

    breaker = Breaker()
    gdcb_mod = types.ModuleType("bot.global_drawdown_circuit_breaker")
    gdcb_mod.get_global_drawdown_cb = lambda: breaker
    monkeypatch.setitem(sys.modules, "bot.global_drawdown_circuit_breaker", gdcb_mod)

    assert patch._attempt_known_false_incident_recovery() is True
    assert ks.active is False
    assert len(ks.deactivate_reasons) == 1
    assert patch.INCIDENT_ID in ks.deactivate_reasons[0]
    assert breaker.baselines == [466.94]
    assert os.environ["NIJA_FALSE_DRAWDOWN_INCIDENT_RECOVERED"] == "1"


def test_recovery_preserves_unknown_active_stop(monkeypatch):
    patch = _load_patch("v91_preserve")
    monkeypatch.setenv("NIJA_V91_FORCE_PRODUCTION", "1")
    patch._PATCHED = True
    patch._RECOVERY_LAST_ATTEMPT = -100.0

    bot = sys.modules.get("bot")
    if bot is None:
        bot = types.ModuleType("bot")
        bot.__path__ = []
        monkeypatch.setitem(sys.modules, "bot", bot)

    class KS:
        _activation_history = [
            {"source": "MANUAL", "reason": "operator emergency", "timestamp": "2026-08-14T20:00:00+00:00"}
        ]

        def is_active(self):
            return True

        def deactivate(self, reason=""):
            raise AssertionError("must not deactivate unknown stop")

    ks_mod = types.ModuleType("bot.kill_switch")
    ks_mod.get_kill_switch = lambda: KS()
    monkeypatch.setitem(sys.modules, "bot.kill_switch", ks_mod)

    assert patch._attempt_known_false_incident_recovery() is False
