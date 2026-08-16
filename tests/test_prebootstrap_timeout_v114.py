from pathlib import Path


def test_v114_build_patcher_raises_only_default_timeout():
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "apply_writer_generation_handoff_v45.py").read_text(encoding="utf-8")

    assert 'NIJA_PREBOOTSTRAP_HANDOFF_TIMEOUT_S", "90"' in text
    assert 'timeout_s = 90.0' in text
    assert 'NIJA_PREBOOTSTRAP_HANDOFF_TIMEOUT_S", "45"' in text
    assert 'timeout_s = 45.0' in text
    assert "_patch_prebootstrap_timeout()" in text
    assert "prebootstrap_timeout_default_s=90" in text


def test_v114_does_not_force_readiness_or_activation():
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "apply_writer_generation_handoff_v45.py").read_text(encoding="utf-8")

    forbidden = (
        'NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"',
        'NIJA_RUNTIME_TRADING_STATE"] = "LIVE"',
        'capital_ready", True',
        'authority_ready", True',
        'bootstrap_ready", True',
    )
    assert all(token not in text for token in forbidden)
