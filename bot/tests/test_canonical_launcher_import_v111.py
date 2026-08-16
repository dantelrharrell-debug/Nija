from pathlib import Path


def _launcher_source() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / "scripts" / "canonical_runtime_launcher_v26.py").read_text(encoding="utf-8")


def test_v111_uses_canonical_import_for_writer_first_modules():
    source = _launcher_source()
    assert 'MARKER = "20260816-canonical-runtime-launcher-v111"' in source
    assert 'bot_entry = _canonical_import("bot.bot")' in source
    assert 'bot_main = _canonical_import("bot.bot_main")' in source
    assert 'authority = _canonical_import("bot.execution_authority_context")' in source


def test_v111_does_not_use_wrapped_import_module_at_writer_first_boundary():
    source = _launcher_source()
    start = source.index("def _bootstrap_writer_first()")
    end = source.index("def _run_main_single_identity", start)
    body = source[start:end]
    assert 'importlib.import_module("bot.bot")' not in body
    assert 'importlib.import_module("bot.bot_main")' not in body
    assert 'importlib.import_module("bot.execution_authority_context")' not in body


def test_v111_keeps_fail_closed_writer_lineage_checks():
    source = _launcher_source()
    assert "canonical writer bootstrap did not establish exact distributed lineage" in source
    assert "exact_authority_reverify_failed" in source
    assert "assert_distributed_writer_authority" in source
