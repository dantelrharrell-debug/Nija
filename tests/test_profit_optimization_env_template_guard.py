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


def test_alternate_secret_names_rejected(tmp_path):
    for name in ("STRIPE_WEBHOOK_TOKEN", "SERVICE_CLIENT_SECRET", "DATABASE_URL", "CUSTOM_CREDENTIAL"):
        template = tmp_path / "template"
        template.write_text(name + "=synthetic-test-placeholder\\n", encoding="utf-8")
        assert module.template_has_populated_credentials(template)


def test_multiline_private_key_is_rejected_without_disclosure(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    marker = "synthetic-key-payload-only"
    (tmp_path / ".env.profit_optimized").write_text(
        "COINBASE_API_SECRET='-----BEGIN EC PRIVATE KEY-----\\n"
        + marker + "\\n-----END EC PRIVATE KEY-----'\\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("PRESERVE=original\\n", encoding="utf-8")
    assert module.setup_env_file() is False
    assert (tmp_path / ".env").read_text() == "PRESERVE=original\\n"
    assert marker not in capsys.readouterr().out


def test_malformed_template_preserves_existing_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.profit_optimized").write_text(
        "SAFE_MODE=1\\nunexpected-continuation-line\\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text("PRESERVE=existing\\n", encoding="utf-8")
    assert module.setup_env_file() is False
    assert (tmp_path / ".env").read_text() == "PRESERVE=existing\\n"
    assert not (tmp_path / ".env.backup").exists()


def test_validated_snapshot_written_when_template_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    template = tmp_path / ".env.profit_optimized"
    template.write_text("SAFE_MODE=paper\\nCOINBASE_API_KEY=\\n", encoding="utf-8")
    original_replace = module.os.replace

    def change_template_then_replace(src, dst):
        template.write_text("COINBASE_API_KEY=synthetic-not-real\\n", encoding="utf-8")
        original_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", change_template_then_replace)
    assert module.setup_env_file() is True
    assert (tmp_path / ".env").read_text() == "SAFE_MODE=paper\\nCOINBASE_API_KEY=\\n"


def test_main_exits_nonzero_when_setup_rejected(monkeypatch):
    import pytest
    monkeypatch.setattr(module, "check_optimization_modules", lambda: True)
    monkeypatch.setattr(module, "show_optimization_features", lambda: None)
    monkeypatch.setattr(module, "setup_env_file", lambda: False)
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 1


def test_unreadable_encoding_rejected(tmp_path):
    template = tmp_path / "template"
    template.write_bytes(b"SAFE_MODE=\\xff\\n")
    assert module.template_has_populated_credentials(template)
