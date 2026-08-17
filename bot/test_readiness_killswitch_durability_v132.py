from __future__ import annotations

import importlib
import os


def test_persisted_retired_heartbeat_is_eligible() -> None:
    mod = importlib.import_module("bot.readiness_killswitch_durability_v132_patch")
    status = {
        "recent_history": [
            {
                "source": "AUTOMATIC",
                "reason": "AUTHORITY_HEARTBEAT_EXPIRED after 3 failures: core_thread_dead — NIJA_CORE_THREAD_ALIVE is not set",
            },
            {"source": "FILE_SYSTEM", "reason": "Kill switch file detected"},
        ]
    }
    eligible, detail = mod._eligible_persisted_retired_stop(status)
    assert eligible is True
    assert "AUTHORITY_HEARTBEAT_EXPIRED" in detail


def test_direct_new_heartbeat_stop_is_never_auto_clear_eligible() -> None:
    mod = importlib.import_module("bot.readiness_killswitch_durability_v132_patch")
    status = {
        "recent_history": [
            {
                "source": "AUTOMATIC",
                "reason": "AUTHORITY_HEARTBEAT_EXPIRED after 3 failures: core_thread_dead",
            }
        ]
    }
    eligible, detail = mod._eligible_persisted_retired_stop(status)
    assert eligible is False
    assert detail == "latest_not_restart_persistence"


def test_manual_stop_behind_persistence_is_preserved() -> None:
    mod = importlib.import_module("bot.readiness_killswitch_durability_v132_patch")
    status = {
        "recent_history": [
            {"source": "MANUAL", "reason": "operator emergency stop"},
            {"source": "FILE_SYSTEM", "reason": "Kill switch file detected"},
        ]
    }
    eligible, detail = mod._eligible_persisted_retired_stop(status)
    assert eligible is False
    assert detail == "causal_source_forbidden"


def test_unrelated_automatic_risk_stop_is_preserved() -> None:
    mod = importlib.import_module("bot.readiness_killswitch_durability_v132_patch")
    status = {
        "recent_history": [
            {"source": "AUTOMATIC", "reason": "daily_loss_limit_exceeded"},
            {"source": "FILE_SYSTEM", "reason": "Kill switch file detected"},
        ]
    }
    eligible, detail = mod._eligible_persisted_retired_stop(status)
    assert eligible is False
    assert detail == "causal_reason_not_retired_heartbeat"


def test_durable_truth_sync_revokes_false_prelive_proofs(monkeypatch) -> None:
    mod = importlib.import_module("bot.readiness_killswitch_durability_v132_patch")
    table = importlib.import_module("bot.readiness_table")

    for key in mod._KEYS:
        table.mark_ready(key)

    monkeypatch.setattr(mod, "_state_value", lambda: "OFF")
    proofs = {key: True for key in mod._KEYS}
    proofs["broker_connected"] = False
    proofs["balance_hydrated"] = False
    proofs["authority_ready"] = False
    proofs["capital_ready"] = False
    proofs["execution_ready"] = False

    ready, pending = mod._durable_truth_sync(proofs)
    snapshot = table.snapshot()
    assert ready is False
    for key in ("broker_connected", "balance_hydrated", "authority_ready", "capital_ready", "execution_ready"):
        assert snapshot[key] is False
        assert key in pending
    assert snapshot["risk_ready"] is True
    assert os.environ["NIJA_AUTHORITY_READY"] == "0"


def test_v131_installer_chains_v132() -> None:
    v131 = importlib.import_module("bot.readiness_killswitch_causality_v131_patch")
    source = open(v131.__file__, "r", encoding="utf-8").read()
    assert "readiness_killswitch_durability_v132_patch" in source
    assert "_install_v132_durability" in source
