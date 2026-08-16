from pathlib import Path


def test_launcher_bootstrap_uses_canonical_import_primitive():
    source = Path("scripts/canonical_runtime_launcher_v26.py").read_text()
    assert 'bot_entry = _canonical_import("bot.bot")' in source
    assert 'bot_main = _canonical_import("bot.bot_main")' in source
    assert 'authority = _canonical_import("bot.execution_authority_context")' in source
    bootstrap_block = source.split("def _bootstrap_writer_first", 1)[1].split("def _run_main_single_identity", 1)[0]
    assert "importlib.import_module(" not in bootstrap_block
    assert "NIJA_CANONICAL_LAUNCHER_IMPORT_V111_READY" in bootstrap_block


def test_launcher_keeps_exact_writer_and_authority_fail_closed_checks():
    source = Path("scripts/canonical_runtime_launcher_v26.py").read_text()
    bootstrap_block = source.split("def _bootstrap_writer_first", 1)[1].split("def _run_main_single_identity", 1)[0]
    assert "_acquire_writer_authority_before_nonce" in bootstrap_block
    assert "canonical writer bootstrap failed" in bootstrap_block
    assert "canonical writer bootstrap did not establish exact distributed lineage" in bootstrap_block
    assert "assert_distributed_writer_authority" in bootstrap_block
    assert "exact_authority_reverify_failed" in bootstrap_block
