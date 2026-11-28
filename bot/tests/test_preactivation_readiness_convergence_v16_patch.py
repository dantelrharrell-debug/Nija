from __future__ import annotations

import importlib
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
import logging


def _module():
    return importlib.import_module("preactivation_readiness_convergence_v16_patch")


def test_marks_every_key_only_when_every_proof_passes(monkeypatch):
    patch = _module()
    marked: list[str] = []
    table = ModuleType("bot.readiness_table")
    table.pending = lambda: [key for key in patch._KEYS if key not in marked]
    table.mark_ready = lambda key: marked.append(key) if key not in marked else None
    monkeypatch.setitem(sys.modules, "bot.readiness_table", table)

    proofs = {key: True for key in patch._KEYS}
    ready, pending = patch._mark_proven_readiness(proofs)
    assert ready is True
    assert pending == []
    assert set(marked) == set(patch._KEYS)
    assert patch.os.environ["NIJA_PREACTIVATION_READINESS_V16_READY"] == "1"
    assert patch.os.environ["NIJA_AUTHORITY_READY"] == "1"
    assert patch.os.environ["NIJA_NONCE_READY"] == "1"

    marked.clear()
    proofs["nonce_ready"] = False
    ready, pending = patch._mark_proven_readiness(proofs)
    assert ready is False
    assert pending == ["nonce_ready"]
    assert marked == []


def test_execution_readiness_requires_live_writer_and_nonce_authority(monkeypatch):
    patch = _module()
    monkeypatch.setattr(
        patch,
        "_capital_snapshot",
        lambda: {"hydrated": True, "stale": False, "real": 100.0, "registered": 1},
    )
    monkeypatch.setattr(
        patch, "_strict_authority_ready", lambda: (False, "runtime_not_acquired")
    )
    monkeypatch.setattr(patch, "_kill_switch_clear", lambda: (True, ""))
    monkeypatch.setattr(patch, "_bootstrap_ready", lambda: (True, []))
    monkeypatch.setattr(patch, "_strategy_published", lambda: True)
    monkeypatch.setattr(patch, "_execution_pipeline_ready", lambda: True)
    monkeypatch.setattr(patch, "_live_mode", lambda: True)
    monkeypatch.setenv("NIJA_PRE_DISPATCH_RISK_SIZING_READY", "1")
    monkeypatch.setenv("NIJA_PRE_DISPATCH_RISK_SIZING_FAIL_CLOSED", "1")
    monkeypatch.setenv("NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED", "1")

    proofs, details = patch._collect_proofs()

    assert proofs["authority_ready"] is False
    assert proofs["nonce_ready"] is False
    assert proofs["execution_ready"] is False
    assert details["execution_pipeline_wired"] is True


def test_rearms_pending_timeout_without_force_transition(monkeypatch):
    patch = _module()
    monkeypatch.delenv("NIJA_ALLOW_PENDING_CONFIRMATION_FORCE_TIMEOUT", raising=False)

    class StateMachine:
        def __init__(self):
            self._lock = threading.RLock()
            self._pending_confirmation_since = 1.0

        def get_current_state(self):
            return SimpleNamespace(value="LIVE_PENDING_CONFIRMATION")

    sm = StateMachine()
    before = time.monotonic()
    patch._rearm_unsafe_timeout(sm)
    assert sm._pending_confirmation_since >= before


def test_activation_uses_normal_commit_path(monkeypatch):
    patch = _module()
    proofs = {key: True for key in patch._KEYS}
    monkeypatch.setattr(patch, "_collect_proofs", lambda: (proofs, {"proof": "ok"}))
    monkeypatch.setattr(patch, "_mark_proven_readiness", lambda value: (True, []))

    class StateMachine:
        def __init__(self):
            self._lock = threading.RLock()
            self._pending_confirmation_since = time.monotonic()
            self.state = "LIVE_PENDING_CONFIRMATION"

        def get_current_state(self):
            return SimpleNamespace(value=self.state)

    sm = StateMachine()
    calls: list[str] = []
    monitor = ModuleType("bot.activation_pending_commit_monitor_patch")
    monitor._state_machine = lambda: sm
    monitor._current_state_value = lambda value: value.state
    monitor._capital_ready_snapshot = lambda: (True, {"real_capital": 100.0})

    def commit_once(value, meta):
        calls.append("commit")
        value.state = "LIVE_ACTIVE"
        return True

    monitor._commit_once = commit_once
    monkeypatch.setitem(sys.modules, "bot.activation_pending_commit_monitor_patch", monitor)

    active, details = patch._attempt_activation()
    assert active is True
    assert calls == ["commit"]
    assert details["state_after"] == "LIVE_ACTIVE"


def test_logs_live_execution_enabled_on_successful_activation(monkeypatch, caplog):
    patch = _module()
    proofs = {key: True for key in patch._KEYS}
    monkeypatch.setattr(patch, "_collect_proofs", lambda: (proofs, {"proof": "ok"}))
    monkeypatch.setattr(patch, "_mark_proven_readiness", lambda value: (True, []))

    class StateMachine:
        def __init__(self):
            self._lock = threading.RLock()
            self.state = "LIVE_PENDING_CONFIRMATION"

    sm = StateMachine()
    monitor = ModuleType("bot.activation_pending_commit_monitor_patch")
    monitor._state_machine = lambda: sm
    monitor._current_state_value = lambda value: value.state
    monitor._capital_ready_snapshot = lambda: (True, {"real_capital": 100.0})
    monitor._commit_once = lambda value, meta: setattr(value, "state", "LIVE_ACTIVE") or True
    monkeypatch.setitem(sys.modules, "bot.activation_pending_commit_monitor_patch", monitor)

    with caplog.at_level(logging.CRITICAL):
        active, _details = patch._attempt_activation()

    assert active is True
    assert "LIVE_EXECUTION_ENABLED authority_ready=True nonce_ready=True activation=committed" in caplog.text

def test_starts_strategy_publication_monitor_once(monkeypatch):
    patch = _module()
    calls: list[str] = []
    publication = ModuleType("bot.strategy_publication_patch")
    publication.start_monitor = lambda: calls.append("start") or True
    monkeypatch.setitem(sys.modules, "bot.strategy_publication_patch", publication)
    patch._STRATEGY_PUBLICATION_MONITOR_STARTED = False

    assert patch._ensure_strategy_publication_monitor() == (True, "started")
    assert patch._ensure_strategy_publication_monitor() == (True, "already_started")
    assert calls == ["start"]


def test_retries_activation_after_strategy_publication(monkeypatch, caplog):
    patch = _module()
    patch._LAST_STRATEGY_PUBLISHED = False
    monkeypatch.setattr(patch, "_live_mode", lambda: True)
    monkeypatch.setattr(
        patch, "_ensure_strategy_publication_monitor", lambda: (True, "started")
    )
    monkeypatch.setenv("NIJA_POST_PUBLICATION_ACTIVATION_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("NIJA_POST_PUBLICATION_ACTIVATION_INITIAL_DELAY_S", "0")
    monkeypatch.setenv("NIJA_POST_PUBLICATION_ACTIVATION_MAX_DELAY_S", "0")
    monkeypatch.setenv("NIJA_POST_PUBLICATION_ACTIVATION_BACKOFF", "1")

    attempts: list[int] = []
    results = iter(
        (
            (
                False,
                {
                    "proofs": {"strategy_ready": True},
                    "pending": ["bootstrap_ready"],
                    "activation": "capital_snapshot_not_accepted",
                },
            ),
            (
                False,
                {
                    "proofs": {"strategy_ready": True},
                    "pending": ["bootstrap_ready"],
                    "activation": "capital_snapshot_not_accepted",
                },
            ),
            (
                True,
                {
                    "proofs": {"strategy_ready": True},
                    "pending": [],
                    "activation": "committed",
                    "state_after": "LIVE_ACTIVE",
                },
            ),
        )
    )

    def fake_attempt():
        attempts.append(len(attempts) + 1)
        return next(results)

    monkeypatch.setattr(patch, "_attempt_activation", fake_attempt)
    monkeypatch.setattr(patch.time, "sleep", lambda _seconds: None)

    with caplog.at_level(logging.WARNING):
        active, details = patch._cycle()

    assert active is True
    assert attempts == [1, 2, 3]
    assert details["state_after"] == "LIVE_ACTIVE"
    assert details["post_publication_retry_attempts"] == 2
    assert "POST_PUBLICATION_ACTIVATION_RETRY attempt=1/3 active=false" in caplog.text
    assert "POST_PUBLICATION_ACTIVATION_RETRY_SUCCESS attempts=2 state=LIVE_ACTIVE" in caplog.text


def test_capital_reporting_does_not_treat_missing_or_placeholder_as_verified_zero():
    v16 = _module()
    assert v16._capital_reporting(SimpleNamespace())["real_capital_usd"] is None
    now = datetime.now(timezone.utc)
    stamp = (now - timedelta(seconds=30)).isoformat()
    expiry = (now + timedelta(seconds=60)).isoformat()
    snapshot = {
        "real_capital": 0.0, "broker_count": 1, "expected_brokers": 1,
        "last_updated": stamp, "is_fresh": True,
        "snapshot_publication": {"timestamp": stamp, "expiry": expiry, "accepted": False, "stale": False},
    }
    authority = SimpleNamespace(get_snapshot=lambda: snapshot)
    report = v16._capital_reporting(authority)
    assert report["status"] == "zero_unverified" and report["real_capital_usd"] is None

    snapshot["real_capital"] = 32.4
    snapshot["snapshot_publication"]["accepted"] = True
    assert v16._capital_reporting(authority)["real_capital_usd"] == 32.4
    snapshot["expected_brokers"] = 2
    assert v16._capital_reporting(authority)["real_capital_usd"] is None
    snapshot["expected_brokers"] = 1
    snapshot["snapshot_publication"]["timestamp"] = "different"
    assert v16._capital_reporting(authority)["real_capital_usd"] is None

    publication = snapshot["snapshot_publication"]
    publication["timestamp"] = stamp
    for invalid_expiry in (None, "invalid", (now - timedelta(seconds=1)).isoformat()):
        publication["expiry"] = invalid_expiry
        assert v16._capital_reporting(authority)["real_capital_usd"] is None

    publication["expiry"] = expiry
    future = (now + timedelta(seconds=15)).isoformat()
    snapshot["last_updated"] = publication["timestamp"] = future
    assert v16._capital_reporting(authority)["real_capital_usd"] is None
