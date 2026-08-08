from __future__ import annotations

import os
from types import ModuleType

import bot.writer_reelection_loss_reason_v46_patch as v46


def test_existing_missing_lock_reason_remains_recoverable() -> None:
    assert v46._safe_recoverable_reason("lock_missing_and_fencing_token_mismatch") is True
    assert v46._safe_recoverable_reason(
        "entrypoint_writer_authority_lost:lock_missing_and_fencing_token_mismatch"
    ) is True


def test_authority_invariant_release_for_reelection_is_recoverable() -> None:
    reason = (
        "writer_lock_released_for_reelection:"
        "authority_invariant_violated:lease_acquired_but_fencing_token_missing "
        "NIJA_WRITER_LEASE_ACQUIRED='1'"
    )
    assert v46._newly_recoverable_reason(reason) is True
    assert v46._safe_recoverable_reason(reason) is True


def test_core_thread_loss_remains_terminal() -> None:
    assert v46._newly_recoverable_reason(
        "writer_lock_released_for_reelection:core_thread_not_alive"
    ) is False
    assert v46._safe_recoverable_reason(
        "writer_lock_released_for_reelection:core_thread_not_alive"
    ) is False
    assert v46._safe_recoverable_reason(
        "writer_lock_released_for_reelection:authority_invariant_violated:core_thread_dead"
    ) is False


def test_arbitrary_heartbeat_or_manual_loss_is_not_recoverable() -> None:
    assert v46._safe_recoverable_reason("heartbeat_grace_expired:redis_timeout") is False
    assert v46._safe_recoverable_reason("manual_operator_stop") is False
    assert v46._safe_recoverable_reason("lock_owned_by_different_writer") is False


def test_v39_predicate_extension_preserves_original_and_adds_narrow_case() -> None:
    module = ModuleType("nija_production_readiness_v39_prebot")
    module.MARKER = "20260807-production-readiness-v39"
    module._recoverable_writer_loss = lambda reason: str(reason) == "legacy-safe"

    assert v46._patch_v39_module(module) is True
    assert module._recoverable_writer_loss("legacy-safe") is True
    assert module._recoverable_writer_loss(
        "writer_lock_released_for_reelection:"
        "authority_invariant_violated:singleton_acquired_but_env_cleared"
    ) is True
    assert module._recoverable_writer_loss("lock_owned_by_different_writer") is False


def test_entrypoint_observability_is_published_before_original_loss_handler(monkeypatch) -> None:
    observed: list[tuple[str, str, str, str]] = []

    class Authority:
        def _mark_lost(self, reason: str) -> None:
            observed.append(
                (
                    str(reason),
                    os.environ.get("NIJA_WRITER_LAST_LOSS_REASON", ""),
                    os.environ.get("NIJA_WRITER_LAST_LOSS_RECOVERABLE", ""),
                    os.environ.get("NIJA_WRITER_LEASE_GENERATION", ""),
                )
            )
            os.environ.pop("NIJA_WRITER_LEASE_GENERATION", None)
            os.environ.pop("NIJA_WRITER_FENCING_TOKEN", None)

    module = ModuleType("bot.entrypoint_writer_authority")
    module.EntrypointWriterAuthority = Authority
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "4412")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token-4412")

    assert v46._patch_entrypoint_module(module) is True
    reason = (
        "writer_lock_released_for_reelection:"
        "authority_invariant_violated:singleton_acquired_but_env_cleared"
    )
    Authority()._mark_lost(reason)

    assert observed == [(reason, reason, "1", "4412")]
    assert os.environ.get("NIJA_WRITER_LAST_LOSS_REASON") == reason
    assert os.environ.get("NIJA_WRITER_LAST_LOSS_RECOVERABLE") == "1"
    assert float(os.environ.get("NIJA_WRITER_LAST_LOSS_TS", "0")) > 0.0
    assert "NIJA_WRITER_LEASE_GENERATION" not in os.environ
    assert "NIJA_WRITER_FENCING_TOKEN" not in os.environ
