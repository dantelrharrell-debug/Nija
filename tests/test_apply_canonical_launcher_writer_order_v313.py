from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "scripts" / "apply_canonical_launcher_v26.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "test_apply_canonical_launcher_writer_order_v313_module",
        PATCHER,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _launcher_fixture() -> str:
    return '''def _bootstrap_writer_first() -> tuple[ModuleType, ModuleType]:
    """Import canonical entrypoint and prove Redis writer authority first."""
    bot_entry = _canonical_import("bot.bot")
    bot_main = _canonical_import("bot.bot_main")
    acquire = getattr(bot_main, "_acquire_writer_authority_before_nonce", None)
    if not callable(acquire):
        raise RuntimeError("canonical writer bootstrap function unavailable")

    if not bool(acquire()):
        raise RuntimeError("canonical writer bootstrap failed")

    runtime = getattr(bot_main, "_writer_authority_runtime", None)
    generation_text = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
    token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
    generation = int(generation_text or "0")
    exact_runtime = bool(runtime is not None and generation > 0 and token)
    if not exact_runtime:
        _release_early_writer(bot_main, reason="runtime_lineage_incomplete")
        raise RuntimeError("canonical writer bootstrap did not establish exact distributed lineage")

    authority = _canonical_import("bot.execution_authority_context")
    authority.assert_distributed_writer_authority()

    os.environ["NIJA_CANONICAL_WRITER_FIRST_V59_READY"] = "1"
    os.environ["NIJA_CANONICAL_LAUNCHER_IMPORT_V111_READY"] = "1"
    LOGGER.critical(
        "CANONICAL_EARLY_WRITER_BOOTSTRAP_VERIFIED marker=%s generation=%s token_prefix=%s "
        "exact_redis_proof=true local_fallback=false runtime_fanout_started=false "
        "bootstrap_import_loader=frozen_bootstrap",
        WRITER_FIRST_MARKER,
        generation,
        token[:8],
    )
    return bot_entry, bot_main


def _install_exchange_rejection_provenance_before_runtime() -> None:
    pass
'''


def test_v313_moves_guarded_bot_entry_import_after_writer_proof() -> None:
    patcher = _load()
    patched = patcher.patch_launcher_text(_launcher_fixture())
    body = patched[
        patched.index("def _bootstrap_writer_first()") :
        patched.index("\ndef _install_exchange_rejection_provenance_before_runtime")
    ]

    assert body.index('_canonical_import("bot.bot_main")') < body.index("acquire()")
    assert body.index("acquire()") < body.index(
        'os.environ["NIJA_CANONICAL_WRITER_FIRST_V59_READY"] = "1"'
    )
    assert body.index(
        'os.environ["NIJA_CANONICAL_WRITER_FIRST_V59_READY"] = "1"'
    ) < body.index('_canonical_import("bot.bot")')
    assert (
        '_release_early_writer(bot_main, reason="bot_entry_import_after_writer_failed")'
        in body
    )


def test_v313_patch_is_idempotent() -> None:
    patcher = _load()
    once = patcher.patch_launcher_text(_launcher_fixture())
    twice = patcher.patch_launcher_text(once)
    assert twice == once


def test_v313_never_synthesizes_writer_token_or_generation() -> None:
    patcher = _load()
    patched = patcher.patch_launcher_text(_launcher_fixture())
    assert 'os.environ["NIJA_WRITER_FENCING_TOKEN"]' not in patched
    assert 'os.environ["NIJA_WRITER_LEASE_GENERATION"]' not in patched
    assert "local_fallback=false" in patched
