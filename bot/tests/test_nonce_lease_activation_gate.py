from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from bot import trading_state_machine as tsm


class _MaturingLease:
    def __init__(self, clock: list[float]) -> None:
        self.clock = clock
        self.fencing_token = ""

    def ensure_writer_lock(self, _key_id: str) -> None:
        return None

    def get_writer_lease_status(self, _key_id: str) -> dict[str, object]:
        return {
            "enabled": True,
            "token": 3074,
            "owner_instance": "writer-a",
            "stable_for_s": self.clock[0],
            "error": "",
        }


def test_nonce_gate_waits_for_same_owner_lease_to_mature(monkeypatch) -> None:
    clock = [28.2]
    manager = _MaturingLease(clock)
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "platform-key")
    monkeypatch.setenv("NIJA_ENFORCE_NONCE_WRITER_LEASE", "true")
    monkeypatch.setenv("NIJA_NONCE_LEASE_STABILITY_MAX_WAIT_S", "5")

    def advance(seconds: float) -> None:
        clock[0] += seconds

    with patch.object(tsm, "_kraken_nonce_gates_required", return_value=True), patch.object(
        tsm, "_nonce_lease_stability_requirement_s", return_value=30.0
    ), patch(
        "bot.distributed_nonce_manager.get_distributed_nonce_manager",
        return_value=manager,
    ), patch(
        "bot.distributed_nonce_manager.make_api_key_id",
        return_value="key-id",
    ), patch(
        "bot.execution_authority_context.assert_startup_write_authority",
        return_value=None,
    ), patch.object(
        tsm.time, "monotonic", side_effect=lambda: clock[0]
    ), patch.object(
        tsm.time, "sleep", side_effect=advance
    ):
        ok, error = tsm._nonce_writer_lease_gate()

    assert ok is True
    assert error == ""
    assert clock[0] >= 30.0
    assert manager.fencing_token == "3074"


def test_nonce_gate_remains_fail_closed_when_ownership_check_fails(monkeypatch) -> None:
    manager = SimpleNamespace(
        ensure_writer_lock=lambda _key_id: (_ for _ in ()).throw(
            RuntimeError("foreign lease owner")
        )
    )
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "platform-key")
    monkeypatch.setenv("NIJA_ENFORCE_NONCE_WRITER_LEASE", "true")
    monkeypatch.setenv("NIJA_NONCE_LEASE_RETRIES", "2")
    monkeypatch.setenv("NIJA_NONCE_LEASE_RETRY_DELAY_S", "0")
    monkeypatch.setenv("NIJA_NONCE_LEASE_STABILITY_MAX_WAIT_S", "1")

    with patch.object(tsm, "_kraken_nonce_gates_required", return_value=True), patch(
        "bot.distributed_nonce_manager.get_distributed_nonce_manager",
        return_value=manager,
    ), patch(
        "bot.distributed_nonce_manager.make_api_key_id",
        return_value="key-id",
    ), patch(
        "bot.execution_authority_context.assert_startup_write_authority",
        return_value=None,
    ):
        ok, error = tsm._nonce_writer_lease_gate()

    assert ok is False
    assert "foreign lease owner" in error
    assert "LIVE_ACTIVE is permitted" in error
