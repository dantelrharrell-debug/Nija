from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import bot.authority_heartbeat_startup_grace_v129_patch as patch


def test_v129_installs_after_v128():
    source = Path(__file__).with_name("bot.py").read_text(encoding="utf-8")
    v128 = source.index("SEAK_NONCE_CAUSALITY_V128")
    v129 = source.index("AUTHORITY_HEARTBEAT_STARTUP_GRACE_V129")
    assert v129 > v128


def test_release_and_marker_are_v129():
    assert patch.MARKER == "20260816-authority-heartbeat-startup-grace-v129"
    assert patch.RELEASE_ID == "20260816-runtime-convergence-v129"


def test_registration_state_latches_after_first_registration():
    patch._CORE_REGISTRATION_OBSERVED = False
    with mock.patch.object(
        patch,
        "_writer_singleton",
        side_effect=[
            SimpleNamespace(_core_thread_registered=False),
            SimpleNamespace(_core_thread_registered=True),
            SimpleNamespace(_core_thread_registered=False),
        ],
    ):
        assert patch._core_registration_state() == (
            False,
            False,
            "startup_not_registered",
        )
        assert patch._core_registration_state() == (True, True, "registered")
        observed, registered, reason = patch._core_registration_state()
        assert observed is True
        assert registered is False
        assert reason == "startup_not_registered"


def test_v129_does_not_resume_seak_clear_shutdown_or_grant_execution():
    source = Path(patch.__file__).read_text(encoding="utf-8")
    assert ".resume(" not in source
    assert "_halt_event.clear(" not in source
    assert 'shutdown_requested"] = ' not in source
    assert "mark_ready(" not in source
    assert 'NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"' not in source
    assert "post_registration_core_death_fatal=true" in source
    assert "redis_authority_still_verified=true" in source


def test_v129_only_neutralizes_core_flag_before_registration():
    source = Path(patch.__file__).read_text(encoding="utf-8")
    assert 'os.environ.pop("NIJA_CORE_THREAD_ALIVE", None)' in source
    assert "not observed_once and not registered_now" in source
    assert "return current(timeout_s)" in source
