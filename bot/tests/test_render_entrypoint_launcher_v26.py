from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_render_entrypoint_applies_launcher_before_bootstrap() -> None:
    text = (ROOT / "scripts" / "render_entrypoint.sh").read_text(encoding="utf-8")
    legacy = "python3 -S scripts/apply_startup_handoff_fix.py"
    v26 = "python3 -S scripts/apply_canonical_launcher_v26.py"
    bootstrap = 'exec bash scripts/production_bootstrap.sh "$@"'
    assert legacy in text
    assert v26 in text
    assert bootstrap in text
    assert text.index(legacy) < text.index(v26) < text.index(bootstrap)
    assert "canonical_runtime_launcher_v26.py" in text
