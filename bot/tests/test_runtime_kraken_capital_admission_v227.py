from __future__ import annotations

import sys
import threading
import types

from bot import runtime_kraken_capital_admission_v227_patch as v227


def _v184_module(*, valid=True, equity=249.04, proof_ts=1000.0, reason="authenticated_tradebalance_equity"):
    module = types.ModuleType("bot.runtime_kraken_aggregate_valuation_confidence_v184_patch")
    module._aggregate_proof_status = lambda _broker: (valid, reason, equity, 1.0)
    return module


def test_validated_equity_requires_positive_current_v184_proof(monkeypatch):
    broker = types.SimpleNamespace(_nija_v184_tradebalance_equity_ts=1000.0)
    module = _v184_module(valid=True, equity=249.04)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    ok, equity, proof_ts, reason = v227._validated_kraken_equity(broker)
    assert ok is True
    assert equity == 249.04
    assert proof_ts == 1000.0
    assert reason == "authenticated_tradebalance_equity"


def test_invalid_or_zero_v184_proof_is_not_admitted(monkeypatch):
    broker = types.SimpleNamespace(_nija_v184_tradebalance_equity_ts=1000.0)
    module = _v184_module(valid=False, equity=249.04, reason="aggregate_proof_stale")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert v227._validated_kraken_equity(broker)[0] is False

    module._aggregate_proof_status = lambda _broker: (True, "ok", 0.0, 0.0)
    assert v227._validated_kraken_equity(broker)[0] is False


def test_same_cycle_provenance_records_exact_authenticated_equity(monkeypatch):
    class Observation(tuple):
        __new__ = staticmethod(lambda cls, value, observed_monotonic, observed_epoch, sequence: tuple.__new__(cls, (value, observed_monotonic, observed_epoch, sequence)))

    refresh = types.SimpleNamespace(live_brokers={"kraken": {"value": 0.0, "sequence": 7}}, excluded_brokers={"kraken": {"reason": "zero"}})
    guard = types.SimpleNamespace(
        _REFRESH_CONTEXT=refresh,
        _BROKER_SEQUENCE={"kraken": 7},
        _OBSERVATIONS={},
        _Observation=Observation,
        _OBSERVATION_LOCK=threading.Lock(),
    )
    batch = types.SimpleNamespace(_nija_v37_resolved={}, _nija_v37_lock=threading.Lock())
    monkeypatch.setattr(v227.time, "time", lambda: 1002.0)
    monkeypatch.setattr(v227.time, "monotonic", lambda: 500.0)

    v227._publish_same_cycle_provenance(guard, batch, 249.04, 1000.0)
    assert refresh.live_brokers["kraken"]["value"] == 249.04
    assert "kraken" not in refresh.excluded_brokers
    assert batch._nija_v37_resolved["kraken"] == 249.04
