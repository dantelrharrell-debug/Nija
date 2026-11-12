"""Regression tests for refusing populated credential templates (offline only)."""
from pathlib import Path
import importlib.util

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/enable_profit_optimization.py"
spec = importlib.util.spec_from_file_location("nija_profit_setup_guard", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_populated_secret_is_rejected_without_value_in_output(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    marker = "test-placeholder-not-a-real-credential"
    (tmp_path / ".env.profit_optimized").write_text(
        "COINBASE_API_KEY=" + marker + "\nRISK_PERCENT=2\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text("PRESERVE=existing\n", encoding="utf-8")
    assert module.setup_env_file() is False
    assert (tmp_path / ".env").read_text() == "PRESERVE=existing\n"
    assert not (tmp_path / ".env.backup").exists()
    assert marker not in capsys.readouterr().out


def test_empty_credentials_allow_safe_copy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = "COINBASE_API_KEY=\nCOINBASE_API_SECRET=\nRISK_PERCENT=2\n"
    (tmp_path / ".env.profit_optimized").write_text(source, encoding="utf-8")
    assert module.setup_env_file() is True
    assert (tmp_path / ".env").read_text(encoding="utf-8") == source


def test_export_and_quoted_credential_values_rejected(tmp_path):
    template = tmp_path / "template"
    template.write_text("export KRAKEN_PLATFORM_API_SECRET='example-placeholder'\n", encoding="utf-8")
    assert module.template_has_populated_credentials(template)


def test_non_credential_settings_allowed(tmp_path):
    template = tmp_path / "template"
    template.write_text("# TOKEN=ignored\nTRADING_MODE=paper\nRISK_PERCENT=1\n", encoding="utf-8")
    assert not module.template_has_populated_credentials(template)
