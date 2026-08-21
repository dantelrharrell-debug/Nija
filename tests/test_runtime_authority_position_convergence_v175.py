from __future__ import annotations

import os
import sys
from types import ModuleType, SimpleNamespace

import bot.runtime_authority_position_convergence_v175_patch as v175


def test_writer_restore_requires_exact_owner(monkeypatch):
    monkeypatch.delenv("NIJA_WRITER_FENCING_TOKEN", raising=False)
    monkeypatch.delenv("NIJA_WRITER_LEASE_GENERATION", raising=False)

    fake_v77 = ModuleType("bot.writer_authority_reconstitution_v77_patch")
    fake_v77.exact_owner_proof = lambda: (None, "redis_lock_owner_mismatch")
    called = {"publish": False}

    def publish_local_lineage(*args, **kwargs):
        called["publish"] = True
        raise AssertionError("must not publish without exact-owner proof")

    fake_v77.publish_local_lineage = publish_local_lineage
    monkeypatch.setitem(sys.modules, fake_v77.__name__, fake_v77)

    ok, reason = v175.restore_writer_lineage_from_exact_owner("test")

    assert ok is False
    assert reason == "redis_lock_owner_mismatch"
    assert called["publish"] is False
    assert os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") == ""


def test_writer_restore_republishes_proven_current_lineage(monkeypatch):
    monkeypatch.delenv("NIJA_WRITER_FENCING_TOKEN", raising=False)
    monkeypatch.delenv("NIJA_WRITER_LEASE_GENERATION", raising=False)

    proof = {"generation": 91, "token": "proven-token", "runtime": object()}
    fake_v77 = ModuleType("bot.writer_authority_reconstitution_v77_patch")
    fake_v77.exact_owner_proof = lambda: (proof, "exact_runtime_redis_owner")

    def publish_local_lineage(received, source):
        assert received is proof
        os.environ["NIJA_WRITER_FENCING_TOKEN"] = "proven-token"
        os.environ["NIJA_WRITER_LEASE_GENERATION"] = "91"
        return True, 91, "exact_owner_reconstituted"

    fake_v77.publish_local_lineage = publish_local_lineage
    monkeypatch.setitem(sys.modules, fake_v77.__name__, fake_v77)

    ok, reason = v175.restore_writer_lineage_from_exact_owner("test")

    assert ok is True
    assert reason == "exact_owner_reconstituted"
    assert os.environ["NIJA_WRITER_FENCING_TOKEN"] == "proven-token"
    assert os.environ["NIJA_WRITER_LEASE_GENERATION"] == "91"


def test_manager_selection_prefers_populated_connected_view(monkeypatch):
    empty = SimpleNamespace(name="empty")
    populated = SimpleNamespace(name="populated")

    monkeypatch.setattr(v175, "_candidate_managers", lambda: [empty, populated])
    monkeypatch.setattr(
        v175,
        "_manager_connected_count",
        lambda manager: 0 if manager is empty else 3,
    )

    assert v175.canonical_manager_with_live_brokers() is populated


def test_manager_selection_does_not_turn_empty_view_into_ready(monkeypatch):
    empty = SimpleNamespace(name="empty")
    monkeypatch.setattr(v175, "_candidate_managers", lambda: [empty])
    monkeypatch.setattr(v175, "_manager_connected_count", lambda manager: 0)

    assert v175.canonical_manager_with_live_brokers() is empty
    assert v175._manager_connected_count(empty) == 0


def test_v175_has_no_safety_bypass_api():
    source = open(v175.__file__, "r", encoding="utf-8").read()
    forbidden = (
        "accept_partial_snapshot",
        "extend_freshness",
        "force_activation",
        "grant_execution_authority",
        "force_trade",
    )
    for token in forbidden:
        assert token not in source
