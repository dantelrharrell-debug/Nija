from __future__ import annotations

import os
import types
from datetime import datetime, timedelta, timezone

from bot import stalled_writer_capital_freshness_v141_patch as v141


class FakeStatus:
    def __init__(self, *, accepted=True, stale=False, reason="accepted", expiry=None):
        self.accepted = accepted
        self.stale = stale
        self.reason = reason
        self.expiry = expiry


class FakeAuthority:
    def __init__(self, status):
        self.status = status

    def get_snapshot_publication_status(self):
        return self.status


def _install_fake_modules(monkeypatch, *, status, legacy_stale=False):
    calls = {"snapshot": 0, "ingest": 0}
    guard = types.ModuleType("bot.stalled_writer_release_guard_v22")

    def legacy_snapshot():
        calls["snapshot"] += 1
        return True, 240.07922401, legacy_stale, 2

    def legacy_ingest(source):
        calls["ingest"] += 1
        return source == "unit_test"

    guard._capital_snapshot = legacy_snapshot
    guard._ingest_authority_snapshot_into_csm = legacy_ingest

    authority = FakeAuthority(status)
    authority_module = types.ModuleType("bot.capital_authority")
    authority_module.get_capital_authority = lambda: authority

    real_import = v141.importlib.import_module

    def fake_import(name):
        if name == "bot.stalled_writer_release_guard_v22":
            return guard
        if name in {"bot.capital_authority", "capital_authority"}:
            return authority_module
        return real_import(name)

    monkeypatch.setattr(v141.importlib, "import_module", fake_import)
    return guard, calls


def test_expired_publication_overrides_sticky_legacy_freshness(monkeypatch):
    now = datetime.now(timezone.utc)
    status = FakeStatus(expiry=now - timedelta(seconds=1))
    guard, calls = _install_fake_modules(monkeypatch, status=status, legacy_stale=False)

    assert v141._patch_stalled_writer_guard() is True
    hydrated, capital, stale, brokers = guard._capital_snapshot()

    assert calls["snapshot"] == 1
    assert hydrated is True
    assert capital == 240.07922401
    assert brokers == 2
    assert stale is True


def test_current_publication_preserves_fresh_capital(monkeypatch):
    now = datetime.now(timezone.utc)
    status = FakeStatus(expiry=now + timedelta(seconds=60))
    guard, _calls = _install_fake_modules(monkeypatch, status=status, legacy_stale=True)

    assert v141._patch_stalled_writer_guard() is True
    hydrated, capital, stale, brokers = guard._capital_snapshot()

    assert hydrated is True
    assert capital == 240.07922401
    assert brokers == 2
    assert stale is False


def test_missing_publication_status_fails_closed(monkeypatch):
    authority = types.SimpleNamespace()
    authority_module = types.ModuleType("bot.capital_authority")
    authority_module.get_capital_authority = lambda: authority
    monkeypatch.setattr(v141.importlib, "import_module", lambda name: authority_module)

    current, reason = v141._publication_current(authority)

    assert current is False
    assert reason == "publication_status_unavailable"


def test_expired_publication_blocks_csm_replay(monkeypatch):
    now = datetime.now(timezone.utc)
    status = FakeStatus(expiry=now - timedelta(seconds=1))
    guard, calls = _install_fake_modules(monkeypatch, status=status)

    assert v141._patch_stalled_writer_guard() is True
    assert guard._ingest_authority_snapshot_into_csm("unit_test") is False
    assert calls["ingest"] == 0


def test_current_publication_allows_existing_csm_replay_path(monkeypatch):
    now = datetime.now(timezone.utc)
    status = FakeStatus(expiry=now + timedelta(seconds=60))
    guard, calls = _install_fake_modules(monkeypatch, status=status)

    assert v141._patch_stalled_writer_guard() is True
    assert guard._ingest_authority_snapshot_into_csm("unit_test") is True
    assert calls["ingest"] == 1


def test_install_preserves_trading_safety_environment(monkeypatch):
    now = datetime.now(timezone.utc)
    status = FakeStatus(expiry=now + timedelta(seconds=60))
    _guard, _calls = _install_fake_modules(monkeypatch, status=status)
    monkeypatch.setattr(v141, "_INSTALLED", False)

    sentinels = {
        "NIJA_RUNTIME_EXECUTION_AUTHORITY": "0",
        "NIJA_NONCE_READY": "1",
        "NIJA_EMERGENCY_STOP": "0",
        "NIJA_PRE_DISPATCH_RISK_SIZING_READY": "1",
    }
    for key, value in sentinels.items():
        monkeypatch.setenv(key, value)

    assert v141.install_import_hook() is True
    assert os.environ["NIJA_STALLED_WRITER_CAPITAL_FRESHNESS_V141_INSTALLED"] == "1"
    for key, value in sentinels.items():
        assert os.environ[key] == value


def test_kill_switch_coordinator_chains_v141() -> None:
    from pathlib import Path
    from bot import kill_switch_coordinator_sync_patch as sync

    source = Path(sync.__file__).read_text(encoding="utf-8")
    assert "stalled_writer_capital_freshness_v141_patch" in source
    assert "runtime_liveness_guards_not_ready" in source
