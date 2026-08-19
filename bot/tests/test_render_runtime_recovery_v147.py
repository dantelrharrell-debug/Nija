from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
START_SCRIPT = ROOT / "start.sh"
RENDER_BLUEPRINT = ROOT / "render.yaml"


def test_render_recovery_is_narrow_and_fail_closed() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    recovery = source[
        source.index("_RENDER_RUNTIME_RECOVERY=false") :
        source.index("# Treat SIGTERM (143) as graceful")
    ]

    assert "0|1|42|75|134|137) _RENDER_RUNTIME_RECOVERABLE=true" in recovery
    assert "143) _RENDER_RUNTIME_RECOVERABLE=true" not in recovery
    assert "_RENDER_RUNTIME_TERMINATION_REQUESTED" in recovery
    assert "RENDER_RUNTIME_TERMINATION_OBSERVED" in recovery
    assert recovery.index("RENDER_RUNTIME_TERMINATION_OBSERVED") < recovery.index(
        "_RENDER_RUNTIME_RECOVERABLE=false"
    )
    assert "writer_authority_bypass=false" in recovery
    assert "NIJA_DEFER_RUNTIME_SITE_HOOKS=1 $PY -u scripts/canonical_runtime_launcher_v26.py" in recovery
    assert "NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK=true" not in recovery
    assert "NIJA_DISABLE_WRITER_LOCK=true" not in recovery
    assert "NIJA_SKIP_STARTUP_PHASE_GATE=true" not in recovery


def test_render_recovery_waits_beyond_the_writer_lease() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")

    assert "(_LEASE_TTL_FOR_RECOVERY_MS + 999) / 1000 + 5" in source
    assert '_RENDER_RUNTIME_RECOVERY_DELAY_S="${NIJA_RENDER_RUNTIME_RECOVERY_DELAY_S:-}"' in source
    assert 'sleep "${_RENDER_RUNTIME_RECOVERY_DELAY_S}"' in source
    assert "_RENDER_RUNTIME_RECOVERY_DELAY_S=15" in source
    assert "_RENDER_RUNTIME_RECOVERY_DELAY_S=120" in source


def test_render_recovery_is_bounded_and_unknown_failures_escape() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")

    assert '_RENDER_RUNTIME_RECOVERY_MAX_ATTEMPTS="${NIJA_RENDER_RUNTIME_RECOVERY_MAX_ATTEMPTS:-12}"' in source
    assert "RENDER_RUNTIME_RECOVERY_EXHAUSTED" in source
    assert '[ "${_RENDER_RUNTIME_RECOVERABLE}" != "true" ]' in source
    assert source.index("RENDER_RUNTIME_RECOVERY_EXHAUSTED") < source.index('echo "❌ Bot crashed! Exit code: $status"')


def test_render_blueprint_pins_recovery_window() -> None:
    source = RENDER_BLUEPRINT.read_text(encoding="utf-8")

    assert "NIJA_RENDER_RUNTIME_RECOVERY_MAX_ATTEMPTS" in source
    assert 'value: "12"' in source
    assert "NIJA_RENDER_RUNTIME_RECOVERY_DELAY_S" in source
    assert 'value: "65"' in source
