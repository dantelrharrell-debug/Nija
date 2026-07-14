from __future__ import annotations

from types import ModuleType

import broker_local_readiness_contract_patch as contract


def _module(monkeypatch, *, missing, statuses, strict=True):
    module = ModuleType("secondary_venue_strict_readiness_patch")
    module.strict_mode_enabled = lambda: strict

    def refresh_readiness(*, force_log=False):
        del force_log
        return True, list(missing), dict(statuses)

    module.refresh_readiness = refresh_readiness
    return module


def _clear(monkeypatch):
    for name in (
        "NIJA_SECONDARY_VENUE_POLICY",
        "NIJA_REQUIRED_VENUES_READY",
        "NIJA_MULTI_BROKER_TRADING_READY",
        "NIJA_GLOBAL_TRADING_READY",
        "NIJA_ACTIVE_LIVE_VENUES",
        "NIJA_REQUIRED_VENUES_MISSING",
        "NIJA_BROKER_LOCAL_READINESS_CONTRACT_INSTALLED",
    ):
        monkeypatch.delenv(name, raising=False)


def test_missing_secondaries_are_reported_not_ready_while_kraken_is_global_ready(monkeypatch):
    _clear(monkeypatch)
    module = _module(
        monkeypatch,
        missing=["coinbase", "okx"],
        statuses={
            "kraken": {"ready": True},
            "coinbase": {"ready": False},
            "okx": {"ready": False},
        },
    )

    assert contract._patch_module(module) is True
    global_ready, missing, statuses = module.refresh_readiness(force_log=True)

    assert global_ready is True
    assert missing == ["coinbase", "okx"]
    assert statuses["kraken"]["ready"] is True
    assert contract.os.environ["NIJA_SECONDARY_VENUE_POLICY"] == "broker_local"
    assert contract.os.environ["NIJA_REQUIRED_VENUES_READY"] == "0"
    assert contract.os.environ["NIJA_GLOBAL_TRADING_READY"] == "1"
    assert contract.os.environ["NIJA_MULTI_BROKER_TRADING_READY"] == "1"
    assert contract.os.environ["NIJA_ACTIVE_LIVE_VENUES"] == "kraken"
    assert contract.os.environ["NIJA_REQUIRED_VENUES_MISSING"] == "coinbase,okx"


def test_no_active_broker_is_globally_not_ready(monkeypatch):
    _clear(monkeypatch)
    module = _module(
        monkeypatch,
        missing=["coinbase", "okx"],
        statuses={
            "coinbase": {"ready": False},
            "okx": {"ready": False},
        },
    )

    contract._patch_module(module)
    global_ready, _missing, _statuses = module.refresh_readiness()

    assert global_ready is False
    assert contract.os.environ["NIJA_REQUIRED_VENUES_READY"] == "0"
    assert contract.os.environ["NIJA_GLOBAL_TRADING_READY"] == "0"
    assert contract.os.environ["NIJA_ACTIVE_LIVE_VENUES"] == ""


def test_all_required_ready_reports_both_required_and_global_ready(monkeypatch):
    _clear(monkeypatch)
    module = _module(
        monkeypatch,
        missing=[],
        statuses={
            "kraken": {"ready": True},
            "coinbase": {"ready": True},
            "okx": {"ready": True},
        },
    )

    contract._patch_module(module)
    global_ready, missing, _statuses = module.refresh_readiness()

    assert global_ready is True
    assert missing == []
    assert contract.os.environ["NIJA_REQUIRED_VENUES_READY"] == "1"
    assert contract.os.environ["NIJA_GLOBAL_TRADING_READY"] == "1"
    assert contract.os.environ["NIJA_ACTIVE_LIVE_VENUES"] == "coinbase,kraken,okx"
