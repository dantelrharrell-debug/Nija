from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_readme_documents_canonical_production_path() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "scripts/production_bootstrap.sh" in readme
    assert "start.sh" in readme
    assert "main.py" in readme
    assert "MultiAccountBrokerManager" in readme
    assert "broker_manager_not_initialized" in (
        ROOT / "docs" / "CANONICAL_STARTUP_RECOVERY_V26.md"
    ).read_text(encoding="utf-8")
