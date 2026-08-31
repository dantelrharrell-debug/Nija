"""Make start.sh launch NIJA through the pre-import v26 runtime launcher.

v313 also hardens the generated Docker image's writer-first ordering. Production
logs on 2026-08-31 proved that ``_bootstrap_writer_first`` imported ``bot.bot``
before importing ``bot.bot_main`` and acquiring the Redis writer lease. The
``bot.bot`` fast-path guards correctly require ``NIJA_WRITER_FENCING_TOKEN`` and
therefore failed closed before the acquisition function could run.

The build patch preserves that guard. It moves only the lightweight
``bot.bot_main`` import ahead of writer acquisition, verifies the exact
non-fallback Redis lineage, publishes the existing canonical writer-first
attestations, and imports ``bot.bot`` only after those proofs exist. If the entry
module import then fails, the writer lease is released and startup still fails
closed. No synthetic token, local fallback, readiness, execution proof, or
activation is introduced.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START_PATH = ROOT / "start.sh"
LAUNCHER_PATH = ROOT / "scripts" / "canonical_runtime_launcher_v26.py"
OLD_LAUNCH = "$PY -u main.py"
NEW_LAUNCH = "$PY -u scripts/canonical_runtime_launcher_v26.py"
MARKER = "20260724-canonical-runtime-launcher-v26"
WRITER_IMPORT_ORDER_MARKER = "20260831-canonical-writer-import-order-v313"

_OLD_WRITER_HEAD = '''def _bootstrap_writer_first() -> tuple[ModuleType, ModuleType]:
    """Import canonical entrypoint and prove Redis writer authority first."""
    bot_entry = _canonical_import("bot.bot")
    bot_main = _canonical_import("bot.bot_main")
    acquire = getattr(bot_main, "_acquire_writer_authority_before_nonce", None)
'''

_NEW_WRITER_HEAD = '''def _bootstrap_writer_first() -> tuple[ModuleType, ModuleType]:
    """Prove Redis writer authority before importing the guarded bot entrypoint."""
    bot_main = _canonical_import("bot.bot_main")
    acquire = getattr(bot_main, "_acquire_writer_authority_before_nonce", None)
'''

_OLD_WRITER_TAIL = '''    os.environ["NIJA_CANONICAL_WRITER_FIRST_V59_READY"] = "1"
    os.environ["NIJA_CANONICAL_LAUNCHER_IMPORT_V111_READY"] = "1"
    LOGGER.critical(
        "CANONICAL_EARLY_WRITER_BOOTSTRAP_VERIFIED marker=%s generation=%s token_prefix=%s "
'''

_NEW_WRITER_TAIL = '''    os.environ["NIJA_CANONICAL_WRITER_FIRST_V59_READY"] = "1"
    os.environ["NIJA_CANONICAL_LAUNCHER_IMPORT_V111_READY"] = "1"
    try:
        bot_entry = _canonical_import("bot.bot")
    except Exception:
        os.environ.pop("NIJA_CANONICAL_WRITER_FIRST_V59_READY", None)
        os.environ.pop("NIJA_CANONICAL_LAUNCHER_IMPORT_V111_READY", None)
        _release_early_writer(bot_main, reason="bot_entry_import_after_writer_failed")
        raise
    LOGGER.critical(
        "CANONICAL_EARLY_WRITER_BOOTSTRAP_VERIFIED marker=%s generation=%s token_prefix=%s "
'''


def patch_text(text: str) -> str:
    """Keep the historical start.sh canonical-launch rewrite idempotent."""
    if NEW_LAUNCH in text:
        patched = text
    elif OLD_LAUNCH in text:
        patched = text.replace(OLD_LAUNCH, NEW_LAUNCH, 1)
    else:
        raise RuntimeError("start.sh canonical Python launch anchor not found")

    if patched.count(NEW_LAUNCH) != 1:
        raise RuntimeError("start.sh must contain exactly one canonical v26 launch")
    if OLD_LAUNCH in patched:
        raise RuntimeError("legacy direct main.py launch remains in start.sh")
    return patched


def patch_launcher_text(text: str) -> str:
    """Make the literal writer-first claim true without weakening its proof gates."""
    patched = text

    if _NEW_WRITER_HEAD not in patched:
        if _OLD_WRITER_HEAD not in patched:
            raise RuntimeError("canonical launcher writer-first head anchor not found")
        patched = patched.replace(_OLD_WRITER_HEAD, _NEW_WRITER_HEAD, 1)

    if _NEW_WRITER_TAIL not in patched:
        if _OLD_WRITER_TAIL not in patched:
            raise RuntimeError("canonical launcher writer-first tail anchor not found")
        patched = patched.replace(_OLD_WRITER_TAIL, _NEW_WRITER_TAIL, 1)

    function_start = patched.index("def _bootstrap_writer_first()")
    function_end = patched.index("\ndef _install_exchange_rejection_provenance_before_runtime", function_start)
    body = patched[function_start:function_end]

    if body.count('_canonical_import("bot.bot_main")') != 1:
        raise RuntimeError("canonical writer bootstrap must import bot.bot_main exactly once")
    if body.count('_canonical_import("bot.bot")') != 1:
        raise RuntimeError("canonical writer bootstrap must import bot.bot exactly once")
    if body.index('_canonical_import("bot.bot_main")') > body.index("acquire()"):
        raise RuntimeError("bot.bot_main must load before writer acquisition")
    if body.index("acquire()") > body.index('os.environ["NIJA_CANONICAL_WRITER_FIRST_V59_READY"] = "1"'):
        raise RuntimeError("writer acquisition must precede writer-first attestation")
    if body.index('os.environ["NIJA_CANONICAL_WRITER_FIRST_V59_READY"] = "1"') > body.index('_canonical_import("bot.bot")'):
        raise RuntimeError("writer-first attestation must precede guarded bot.bot import")
    if "_release_early_writer(bot_main, reason=\"bot_entry_import_after_writer_failed\")" not in body:
        raise RuntimeError("bot entry import failure must release early writer lease")

    return patched


def main() -> None:
    original_start = START_PATH.read_text(encoding="utf-8")
    patched_start = patch_text(original_start)
    START_PATH.write_text(patched_start, encoding="utf-8")

    original_launcher = LAUNCHER_PATH.read_text(encoding="utf-8")
    patched_launcher = patch_launcher_text(original_launcher)
    LAUNCHER_PATH.write_text(patched_launcher, encoding="utf-8")

    print(
        "CANONICAL_RUNTIME_LAUNCHER_V26_PATCH_APPLIED "
        f"marker={MARKER} launch=scripts/canonical_runtime_launcher_v26.py "
        f"start_changed={patched_start != original_start} idempotent=true"
    )
    print(
        "CANONICAL_WRITER_IMPORT_ORDER_V313_PATCH_APPLIED "
        f"marker={WRITER_IMPORT_ORDER_MARKER} "
        f"launcher_changed={patched_launcher != original_launcher} "
        "writer_acquired_before_bot_entry=true exact_redis_proof_preserved=true "
        "local_fallback=false entry_import_failure_releases_writer=true "
        "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false"
    )


if __name__ == "__main__":
    main()
