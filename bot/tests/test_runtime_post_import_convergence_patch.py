from __future__ import annotations

import os
import sys
from types import ModuleType

import bot.runtime_post_import_convergence_patch as patch


def test_broker_local_policy_requires_one_broker(monkeypatch):
    monkeypatch.setenv("NIJA_SECONDARY_VENUE_POLICY", "broker_local")
    monkeypatch.delenv("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS", raising=False)
    assert patch._required_broker_count() == 1
    assert patch._apply_broker_threshold() == 1
    assert os.environ["NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS"] == "1"


def test_global_all_required_policy_keeps_two_brokers(monkeypatch):
    monkeypatch.setenv("NIJA_SECONDARY_VENUE_POLICY", "global_all_required")
    monkeypatch.delenv("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS", raising=False)
    assert patch._required_broker_count() == 2
    assert patch._apply_broker_threshold() == 2


def test_legacy_default_two_is_lowered_for_broker_local(monkeypatch):
    monkeypatch.setenv("NIJA_SECONDARY_VENUE_POLICY", "broker_local")
    monkeypatch.setenv("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS", "2")
    assert patch._apply_broker_threshold() == 1
    assert os.environ["NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS"] == "1"


def test_downstream_risk_alias_drift_is_repaired(monkeypatch):
    canonical = ModuleType("bot.downstream_risk_governor_equity_repair_patch")
    canonical._MARKER = "20260714-downstream-risk-v2"
    drifted = ModuleType("nija_downstream_risk_governor_equity_repair_patch")
    monkeypatch.setitem(sys.modules, patch._CANONICAL, canonical)
    monkeypatch.setitem(sys.modules, patch._ALIAS, drifted)

    assert patch._canonicalize_alias() is True
    assert sys.modules[patch._ALIAS] is canonical
    assert patch._canonicalize_alias() is False
