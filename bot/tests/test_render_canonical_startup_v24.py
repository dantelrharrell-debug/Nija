from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_render_and_docker_use_self_verifying_entrypoint():
    render_yaml = (ROOT / "render.yaml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "dockerCommand: bash scripts/render_entrypoint.sh" in render_yaml
    assert 'CMD ["bash", "scripts/render_entrypoint.sh"]' in dockerfile
    assert "bot/canonical_broker_startup_convergence_v24.py" in dockerfile
    assert "bot/live_broker_profit_exit_convergence_v25.py" in dockerfile
    assert "bot/live_engine_profit_exit_convergence_v25.py" in dockerfile


def test_render_entrypoint_applies_source_handoff_and_compiles_v24():
    entrypoint = (ROOT / "scripts" / "render_entrypoint.sh").read_text(
        encoding="utf-8"
    )

    assert "python3 -S scripts/apply_startup_handoff_fix.py" in entrypoint
    assert "bot/canonical_broker_startup_convergence_v24.py" in entrypoint
    assert "RENDER_ENTRYPOINT_CANONICAL_HANDOFF_READY" in entrypoint
    assert 'exec bash scripts/production_bootstrap.sh "$@"' in entrypoint


def test_secondary_venue_failure_is_broker_local_in_render_blueprint():
    render_yaml = (ROOT / "render.yaml").read_text(encoding="utf-8")
    block = render_yaml.split("- key: NIJA_REQUIRE_SECONDARY_VENUES_READY", 1)[1]

    assert 'value: "false"' in block.split("- key:", 1)[0]
    assert "NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS" in render_yaml


def test_attestation_requires_v25_exit_safety_and_v24_startup_guard():
    attestation = (ROOT / "scripts" / "runtime_entrypoint_attestation.py").read_text(
        encoding="utf-8"
    )

    assert "20260723-runtime-entrypoint-attestation-v25" in attestation
    assert "bot/canonical_broker_startup_convergence_v24.py" in attestation
    assert "bot/live_broker_profit_exit_convergence_v25.py" in attestation
    assert "bot/live_engine_profit_exit_convergence_v25.py" in attestation
    assert "bot/logging_format_guard_patch.py" in attestation
    assert "CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_INSTALL_REQUESTED" in attestation
