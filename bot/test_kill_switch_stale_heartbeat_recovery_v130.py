from pathlib import Path

import bot.kill_switch_stale_heartbeat_recovery_v130_patch as patch


def test_v130_installs_after_v129():
    source = Path(__file__).with_name("bot.py").read_text(encoding="utf-8")
    assert source.index("AUTHORITY_HEARTBEAT_STARTUP_GRACE_V129") < source.index(
        "KILL_SWITCH_STALE_HEARTBEAT_RECOVERY_V130"
    )


def test_only_retired_heartbeat_reason_is_recoverable():
    reason = (
        "AUTHORITY_HEARTBEAT_EXPIRED: AUTHORITY HEARTBEAT EXPIRED: "
        "3 consecutive heartbeat failures. Last error: core_thread_dead — "
        "NIJA_CORE_THREAD_ALIVE is not set"
    )
    assert patch._is_retired_heartbeat_stop(reason, "AUTO") is True
    assert patch._is_retired_heartbeat_stop(reason, "MANUAL") is False
    assert patch._is_retired_heartbeat_stop(reason, "UI") is False
    assert patch._is_retired_heartbeat_stop(reason, "CLI") is False
    assert patch._is_retired_heartbeat_stop(reason, "FILE_SYSTEM") is False
    assert patch._is_retired_heartbeat_stop("daily loss limit exceeded", "AUTO") is False
    assert patch._is_retired_heartbeat_stop("unexpected balance delta", "AUTO") is False


def test_latest_activation_ignores_deactivation_history_entries():
    status = {
        "recent_history": [
            {"reason": "old", "source": "AUTO"},
            {"reason": "manual deactivation"},
            {"reason": "new", "source": "AUTO"},
        ]
    }
    assert patch._latest_activation(status) == ("new", "AUTO")


def test_v130_safety_contract_is_fail_closed():
    source = Path(patch.__file__).read_text(encoding="utf-8")
    assert '"MANUAL", "UI", "CLI", "FILE_SYSTEM"' in source
    assert "AUTHORITY_HEARTBEAT_EXPIRED" in source
    assert "core_thread_dead" in source
    assert "NIJA_AUTHORITY_HEARTBEAT_STARTUP_GRACE_V129_INSTALLED" in source
    assert "authority_ready" in source
    assert "execution_ready" in source
    assert "nonce_ready" in source
    assert "seak_halted" in source
    assert "generic_auto_clear=false" in source
    assert "canonical_activation_required=true" in source
    assert "NIJA_RUNTIME_EXECUTION_AUTHORITY\"] = \"1\"" not in source
    assert "mark_ready(" not in source


def test_release_and_marker_are_v130():
    assert patch.MARKER == "20260816-kill-switch-stale-heartbeat-recovery-v130"
    assert patch.RELEASE_ID == "20260816-runtime-convergence-v130"
