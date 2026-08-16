from __future__ import annotations

import importlib
import os
import sys
import time
from types import SimpleNamespace


def _load_v16():
    return importlib.import_module("preactivation_readiness_convergence_v16_patch")


def _clear_handoff() -> None:
    for key in (
        "NIJA_CAPITAL_READINESS_HANDOFF_V34",
        "NIJA_CAPITAL_HANDOFF_REAL",
        "NIJA_CAPITAL_HANDOFF_BROKER_COUNT",
        "NIJA_CAPITAL_HANDOFF_ACCEPTED_TS",
        "NIJA_CAPITAL_HANDOFF_TTL_S",
    ):
        os.environ.pop(key, None)


def test_fresh_handoff_is_accepted_only_as_positive_snapshot_proof(monkeypatch):
    v16 = _load_v16()
    _clear_handoff()
    os.environ["NIJA_CAPITAL_READINESS_HANDOFF_V34"] = "1"
    os.environ["NIJA_CAPITAL_HANDOFF_REAL"] = "395.29"
    os.environ["NIJA_CAPITAL_HANDOFF_BROKER_COUNT"] = "3"
    os.environ["NIJA_CAPITAL_HANDOFF_ACCEPTED_TS"] = str(time.time())
    os.environ["NIJA_CAPITAL_HANDOFF_TTL_S"] = "90"

    proof = v16._fresh_capital_handoff()
    assert proof is not None
    assert proof["hydrated"] is True
    assert proof["stale"] is False
    assert proof["real"] == 395.29
    assert proof["registered"] == 3
    assert proof["source"] == "csm_v2_handoff_v109"


def test_stale_handoff_is_rejected(monkeypatch):
    v16 = _load_v16()
    _clear_handoff()
    os.environ["NIJA_CAPITAL_READINESS_HANDOFF_V34"] = "1"
    os.environ["NIJA_CAPITAL_HANDOFF_REAL"] = "395.29"
    os.environ["NIJA_CAPITAL_HANDOFF_BROKER_COUNT"] = "3"
    os.environ["NIJA_CAPITAL_HANDOFF_ACCEPTED_TS"] = str(time.time() - 120.0)
    os.environ["NIJA_CAPITAL_HANDOFF_TTL_S"] = "90"
    assert v16._fresh_capital_handoff() is None


def test_zero_or_unregistered_handoff_is_rejected(monkeypatch):
    v16 = _load_v16()
    _clear_handoff()
    os.environ["NIJA_CAPITAL_READINESS_HANDOFF_V34"] = "1"
    os.environ["NIJA_CAPITAL_HANDOFF_REAL"] = "0"
    os.environ["NIJA_CAPITAL_HANDOFF_BROKER_COUNT"] = "3"
    os.environ["NIJA_CAPITAL_HANDOFF_ACCEPTED_TS"] = str(time.time())
    assert v16._fresh_capital_handoff() is None

    os.environ["NIJA_CAPITAL_HANDOFF_REAL"] = "395.29"
    os.environ["NIJA_CAPITAL_HANDOFF_BROKER_COUNT"] = "0"
    assert v16._fresh_capital_handoff() is None


def test_live_capital_authority_truth_wins_over_handoff(monkeypatch):
    v16 = _load_v16()
    _clear_handoff()
    os.environ["NIJA_CAPITAL_READINESS_HANDOFF_V34"] = "1"
    os.environ["NIJA_CAPITAL_HANDOFF_REAL"] = "999.00"
    os.environ["NIJA_CAPITAL_HANDOFF_BROKER_COUNT"] = "9"
    os.environ["NIJA_CAPITAL_HANDOFF_ACCEPTED_TS"] = str(time.time())

    authority = SimpleNamespace(
        is_hydrated=True,
        total_capital=395.29,
        real_capital=395.29,
        available_capital=390.0,
        registered_broker_count=3,
        valid_broker_count=3,
        broker_values={"kraken": 155.21, "coinbase": 95.12, "okx": 144.96},
        stale=False,
    )
    module = SimpleNamespace(get_capital_authority=lambda: authority)
    monkeypatch.setitem(sys.modules, "bot.capital_authority", module)

    snapshot = v16._capital_snapshot()
    assert snapshot["source"] == "capital_authority"
    assert snapshot["real"] == 395.29
    assert snapshot["registered"] == 3


def test_handoff_bridges_temporary_authority_publication_lag(monkeypatch):
    v16 = _load_v16()
    _clear_handoff()
    os.environ["NIJA_CAPITAL_READINESS_HANDOFF_V34"] = "1"
    os.environ["NIJA_CAPITAL_HANDOFF_REAL"] = "395.29"
    os.environ["NIJA_CAPITAL_HANDOFF_BROKER_COUNT"] = "3"
    os.environ["NIJA_CAPITAL_HANDOFF_ACCEPTED_TS"] = str(time.time())
    os.environ["NIJA_CAPITAL_HANDOFF_TTL_S"] = "90"

    authority = SimpleNamespace(
        is_hydrated=False,
        total_capital=0.0,
        real_capital=0.0,
        available_capital=0.0,
        registered_broker_count=0,
        valid_broker_count=0,
        broker_values={},
        stale=False,
    )
    module = SimpleNamespace(get_capital_authority=lambda: authority)
    monkeypatch.setitem(sys.modules, "bot.capital_authority", module)

    snapshot = v16._capital_snapshot()
    assert snapshot["source"] == "csm_v2_handoff_v109"
    assert snapshot["hydrated"] is True
    assert snapshot["real"] == 395.29
    assert snapshot["registered"] == 3
