from pathlib import Path


def _read(rel: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / rel).read_text(encoding="utf-8")


def test_v113_installs_before_v60_in_fast_path():
    source = _read("bot/bot.py")
    compat = source.index('("bot.final_activation_v60_v16_compat_v113_patch", "FINAL_ACTIVATION_V60_V16_COMPAT_V113")')
    v60 = source.index('("bot.final_production_activation_repair_v60_patch", "FINAL_PRODUCTION_ACTIVATION_V60")')
    assert compat < v60


def test_v113_targets_current_v16_attempt_activation_api():
    source = _read("bot/final_activation_v60_v16_compat_v113_patch.py")
    assert 'getattr(v16, "_attempt_activation", None)' in source
    assert 'v16._attempt_activation = attempt_activation' in source
    assert 'getattr(v16, "_cycle", None)' not in source


def test_v113_keeps_proof_and_fail_closed_activation_path():
    source = _read("bot/final_activation_v60_v16_compat_v113_patch.py")
    assert "v16._collect_proofs()" in source
    assert "v16._mark_proven_readiness(proofs)" in source
    assert 'v60.request_activation("v16_readiness_complete")' in source
    assert "force_activation=false" in source
