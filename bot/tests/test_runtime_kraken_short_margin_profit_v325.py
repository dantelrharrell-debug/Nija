from __future__ import annotations

from types import SimpleNamespace

from bot import runtime_kraken_short_margin_profit_v325_patch as v325


class _KrakenBroker:
    broker_type = SimpleNamespace(value="kraken")


class _ExecutionEngine:
    def __init__(self, user_id="platform"):
        self.user_id = user_id


class _Strategy:
    def __init__(self, account_id="platform"):
        self.broker_client = _KrakenBroker()
        self.execution_engine = _ExecutionEngine(account_id)

    def _get_broker_name(self):
        return "kraken"


class _FakeMarginEngine:
    def __init__(self, *, permission="CONFIRMED", allowed=True, leverages=(2,), health_reason="healthy"):
        self.permission = permission
        self.allowed = allowed
        self.leverages = tuple(leverages)
        self.health_reason = health_reason
        self.invalidations = 0

    def check_permissions(self, adapter):
        return self.permission

    def invalidate_health_cache(self):
        self.invalidations += 1

    def is_margin_trade_allowed(self, *, is_reducing=False, adapter=None):
        return self.allowed, self.health_reason

    def get_pair_leverages(self, symbol, side, adapter=None):
        assert side == "sell"
        return self.leverages


def _install_fake_margin_module(monkeypatch, engine):
    permission = SimpleNamespace(CONFIRMED="CONFIRMED")
    fake = SimpleNamespace(
        get_margin_engine=lambda account_id, adapter=None: engine,
        MarginPermissionState=permission,
    )
    real_import = v325.importlib.import_module

    def import_module(name):
        if name == "bot.kraken_margin_engine":
            return fake
        return real_import(name)

    monkeypatch.setattr(v325.importlib, "import_module", import_module)
    monkeypatch.setattr(v325, "_execution_authority_ready", lambda: (True, "ready"))
    with v325._PROOF_LOCK:
        v325._PROOF_CACHE.clear()


def test_kraken_short_proof_requires_feature_enabled(monkeypatch):
    _install_fake_margin_module(monkeypatch, _FakeMarginEngine())
    monkeypatch.setenv("NIJA_KRAKEN_MARGIN_ENABLED", "true")
    monkeypatch.setenv("NIJA_KRAKEN_SHORT_MARGIN_ENABLED", "false")
    ok, reason, leverage = v325._kraken_short_margin_proof(_Strategy(), "BTC-USD")
    assert not ok
    assert reason == "kraken_short_margin_disabled"
    assert leverage == 1


def test_kraken_short_proof_requires_permission(monkeypatch):
    _install_fake_margin_module(monkeypatch, _FakeMarginEngine(permission="DENIED"))
    monkeypatch.setenv("NIJA_KRAKEN_MARGIN_ENABLED", "true")
    monkeypatch.setenv("NIJA_KRAKEN_SHORT_MARGIN_ENABLED", "true")
    ok, reason, _ = v325._kraken_short_margin_proof(_Strategy(), "BTC-USD")
    assert not ok
    assert "margin_permission=DENIED" in reason


def test_kraken_short_proof_requires_healthy_margin(monkeypatch):
    _install_fake_margin_module(
        monkeypatch,
        _FakeMarginEngine(allowed=False, health_reason="maintenance_low"),
    )
    monkeypatch.setenv("NIJA_KRAKEN_MARGIN_ENABLED", "true")
    monkeypatch.setenv("NIJA_KRAKEN_SHORT_MARGIN_ENABLED", "true")
    ok, reason, _ = v325._kraken_short_margin_proof(_Strategy(), "BTC-USD")
    assert not ok
    assert reason == "margin_health=maintenance_low"


def test_kraken_short_proof_requires_pair_leverage_sell(monkeypatch):
    _install_fake_margin_module(monkeypatch, _FakeMarginEngine(leverages=()))
    monkeypatch.setenv("NIJA_KRAKEN_MARGIN_ENABLED", "true")
    monkeypatch.setenv("NIJA_KRAKEN_SHORT_MARGIN_ENABLED", "true")
    ok, reason, _ = v325._kraken_short_margin_proof(_Strategy(), "BTC-USD")
    assert not ok
    assert reason == "pair_leverage_sell_unavailable"


def test_kraken_short_proof_passes_with_exact_account_pair_proof(monkeypatch):
    engine = _FakeMarginEngine(leverages=(2, 3), health_reason="margin_healthy:500%")
    _install_fake_margin_module(monkeypatch, engine)
    monkeypatch.setenv("NIJA_KRAKEN_MARGIN_ENABLED", "true")
    monkeypatch.setenv("NIJA_KRAKEN_SHORT_MARGIN_ENABLED", "true")
    monkeypatch.setenv("NIJA_KRAKEN_MARGIN_DEFAULT_LEVERAGE", "2")
    ok, reason, leverage = v325._kraken_short_margin_proof(
        _Strategy("user-123"),
        "ETH-USD",
        force_fresh_health=True,
    )
    assert ok
    assert reason.startswith("margin_short_proven:")
    assert leverage == 2
    assert engine.invalidations == 1


def test_derivatives_do_not_use_spot_margin_bridge(monkeypatch):
    _install_fake_margin_module(monkeypatch, _FakeMarginEngine())
    monkeypatch.setenv("NIJA_KRAKEN_SHORT_MARGIN_ENABLED", "true")
    ok, reason, leverage = v325._kraken_short_margin_proof(_Strategy(), "BTC-PERP")
    assert not ok
    assert reason == "derivative_uses_existing_short_path"
    assert leverage == 1


def test_proof_is_account_scoped(monkeypatch):
    calls = []

    class _AccountAwareEngine(_FakeMarginEngine):
        pass

    engines = {
        "platform": _AccountAwareEngine(leverages=(2,)),
        "user-9": _AccountAwareEngine(leverages=()),
    }
    permission = SimpleNamespace(CONFIRMED="CONFIRMED")
    fake = SimpleNamespace(
        get_margin_engine=lambda account_id, adapter=None: (calls.append(account_id) or engines[account_id]),
        MarginPermissionState=permission,
    )
    real_import = v325.importlib.import_module

    def import_module(name):
        if name == "bot.kraken_margin_engine":
            return fake
        return real_import(name)

    monkeypatch.setattr(v325.importlib, "import_module", import_module)
    monkeypatch.setattr(v325, "_execution_authority_ready", lambda: (True, "ready"))
    monkeypatch.setenv("NIJA_KRAKEN_MARGIN_ENABLED", "true")
    monkeypatch.setenv("NIJA_KRAKEN_SHORT_MARGIN_ENABLED", "true")
    with v325._PROOF_LOCK:
        v325._PROOF_CACHE.clear()

    ok_platform, _, _ = v325._kraken_short_margin_proof(_Strategy("platform"), "BTC-USD")
    ok_user, _, _ = v325._kraken_short_margin_proof(_Strategy("user-9"), "BTC-USD")
    assert ok_platform
    assert not ok_user
    assert calls == ["platform", "user-9"]
