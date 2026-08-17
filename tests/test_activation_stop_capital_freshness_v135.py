from __future__ import annotations

import os
import sys
import types
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot import activation_stop_capital_freshness_v135_patch as v135


@dataclass(frozen=True)
class FakeStatus:
    accepted: bool
    stale: bool
    reason: str
    timestamp: datetime | None
    expiry: datetime | None


def test_publication_status_turns_stale_after_immutable_expiry() -> None:
    now = datetime(2026, 8, 17, 19, 27, 30, tzinfo=timezone.utc)
    status = FakeStatus(
        accepted=True,
        stale=False,
        reason="accepted",
        timestamp=now - timedelta(minutes=6),
        expiry=now - timedelta(minutes=4),
    )

    converged = v135._status_with_runtime_expiry(status, FakeStatus, now=now)

    assert converged.accepted is True
    assert converged.stale is True
    assert converged.reason == "expired_after_publish"
    assert converged.timestamp == status.timestamp
    assert converged.expiry == status.expiry


def test_publication_status_remains_fresh_before_expiry() -> None:
    now = datetime(2026, 8, 17, 19, 20, 0, tzinfo=timezone.utc)
    status = FakeStatus(
        accepted=True,
        stale=False,
        reason="accepted",
        timestamp=now - timedelta(seconds=10),
        expiry=now + timedelta(seconds=80),
    )

    assert v135._status_with_runtime_expiry(status, FakeStatus, now=now) is status


def test_publication_status_does_not_unstale_rejected_snapshot() -> None:
    now = datetime(2026, 8, 17, 19, 20, 0, tzinfo=timezone.utc)
    status = FakeStatus(
        accepted=False,
        stale=True,
        reason="snapshot_not_newer",
        timestamp=now - timedelta(seconds=20),
        expiry=now + timedelta(seconds=70),
    )

    assert v135._status_with_runtime_expiry(status, FakeStatus, now=now) is status


def _fake_tsm(active, original_result: bool = True) -> tuple[types.ModuleType, list[str], list[str]]:
    module = types.ModuleType("bot.trading_state_machine")
    original_calls: list[str] = []
    revocations: list[str] = []

    def original() -> bool:
        original_calls.append("called")
        return original_result

    module._is_authority_ready = original
    module._kill_switch_is_active = lambda: (active, "test_stop")
    return module, original_calls, revocations


def test_active_kill_switch_blocks_writer_only_authority_bootstrap(monkeypatch) -> None:
    tsm, original_calls, revocations = _fake_tsm(True)
    monkeypatch.setattr(v135, "_revoke_authority", revocations.append)

    assert v135._patch_tsm_authority(tsm)
    assert tsm._is_authority_ready() is False
    assert original_calls == []
    assert revocations == ["v135_kill_switch_active"]


def test_unknown_kill_switch_state_fails_closed(monkeypatch) -> None:
    tsm, original_calls, revocations = _fake_tsm(None)
    monkeypatch.setattr(v135, "_revoke_authority", revocations.append)

    assert v135._patch_tsm_authority(tsm)
    assert tsm._is_authority_ready() is False
    assert original_calls == []
    assert revocations == ["v135_kill_switch_state_unknown"]


def test_clear_kill_switch_delegates_to_existing_authority_proof(monkeypatch) -> None:
    tsm, original_calls, revocations = _fake_tsm(False, original_result=True)
    monkeypatch.setattr(v135, "_revoke_authority", revocations.append)

    assert v135._patch_tsm_authority(tsm)
    assert tsm._is_authority_ready() is True
    assert original_calls == ["called"]
    assert revocations == []


def test_protected_stop_patch_does_not_mutate_nonce_or_execution_env(monkeypatch) -> None:
    tsm, _, revocations = _fake_tsm(True)
    monkeypatch.setattr(v135, "_revoke_authority", revocations.append)
    monkeypatch.setenv("NIJA_NONCE_READY", "1")
    monkeypatch.setenv("NIJA_RUNTIME_NONCE_READY", "1")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")

    assert v135._patch_tsm_authority(tsm)
    assert tsm._is_authority_ready() is False
    assert os.environ["NIJA_NONCE_READY"] == "1"
    assert os.environ["NIJA_RUNTIME_NONCE_READY"] == "1"
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"


def test_v78_is_required_and_installed_fail_closed(monkeypatch) -> None:
    fake = types.ModuleType("bot.capital_refresh_live_continuity_v78_patch")

    def install_import_hook() -> bool:
        os.environ["NIJA_CAPITAL_REFRESH_LIVE_CONTINUITY_V78_INSTALLED"] = "1"
        return True

    fake.install_import_hook = install_import_hook
    monkeypatch.setitem(sys.modules, "bot.capital_refresh_live_continuity_v78_patch", fake)
    monkeypatch.delenv("NIJA_CAPITAL_REFRESH_LIVE_CONTINUITY_V78_INSTALLED", raising=False)

    assert v135._install_v78() is True
    assert os.environ["NIJA_CAPITAL_REFRESH_LIVE_CONTINUITY_V78_INSTALLED"] == "1"


def test_release_manifest_statically_wires_v78_v135_and_successors_through_v137() -> None:
    from bot import runtime_release_manifest_patch as manifest

    assert manifest.RELEASE_ID == "20260817-runtime-convergence-v137"
    assert (
        "bot.capital_refresh_live_continuity_v78_patch",
        "install_import_hook",
    ) in manifest._INSTALLERS
    assert (
        "bot.activation_stop_capital_freshness_v135_patch",
        "install_import_hook",
    ) in manifest._INSTALLERS
    assert (
        "bot.activation_publication_convergence_v136_patch",
        "install_import_hook",
    ) in manifest._INSTALLERS
    assert (
        "bot.capital_publication_deadline_v137_patch",
        "install_import_hook",
    ) in manifest._INSTALLERS
    assert manifest._REQUIRED_FLAGS["capital_refresh_live_continuity_v78"] == (
        "NIJA_CAPITAL_REFRESH_LIVE_CONTINUITY_V78_INSTALLED"
    )
    assert manifest._REQUIRED_FLAGS["activation_stop_capital_freshness_v135"] == (
        "NIJA_ACTIVATION_STOP_CAPITAL_FRESHNESS_V135_INSTALLED"
    )
    assert manifest._REQUIRED_FLAGS["activation_publication_convergence_v136"] == (
        "NIJA_ACTIVATION_PUBLICATION_CONVERGENCE_V136_INSTALLED"
    )
    assert manifest._REQUIRED_FLAGS["capital_publication_deadline_v137"] == (
        "NIJA_CAPITAL_PUBLICATION_DEADLINE_V137_INSTALLED"
    )
