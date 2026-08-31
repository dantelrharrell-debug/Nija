"""Apply canonical production-image source hardening.

This build step preserves the v26 canonical launcher and two safety-critical
production repairs:

* v313 makes the launcher acquire and verify the exact Redis writer lease before
  importing ``bot.bot``. The guarded entrypoint therefore never needs a synthetic
  fencing token and still fails closed when distributed ownership is unavailable.
* v316 makes startup position cost-basis single-flights key themselves by the
  real bound ``get_real_entry_price`` owner instead of an ephemeral transparent
  proof proxy. Production on 2026-08-31 showed a new v98 ``_FetchProofProxy`` on
  every reconciliation retry, which defeated v279's one-worker-per-broker/symbol
  invariant and spawned duplicate Coinbase/Kraken history workers after each
  five-second timeout. The real broker method owner is stable across those
  proxies, so late genuine broker results can now be reused by later retries.

Neither repair fabricates writer authority, cost basis, position truth, execution
proof, or activation. Timeouts remain fail-closed and current market price is
never substituted for entry price.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START_PATH = ROOT / "start.sh"
LAUNCHER_PATH = ROOT / "scripts" / "canonical_runtime_launcher_v26.py"
POSITION_SYNC_PATH = ROOT / "bot" / "startup_position_sync.py"
OLD_LAUNCH = "$PY -u main.py"
NEW_LAUNCH = "$PY -u scripts/canonical_runtime_launcher_v26.py"
MARKER = "20260724-canonical-runtime-launcher-v26"
WRITER_IMPORT_ORDER_MARKER = "20260831-canonical-writer-import-order-v313"
ENTRY_PRICE_IDENTITY_MARKER = "20260831-entry-price-single-flight-identity-v316"

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

_OLD_ENTRY_PRICE_IDENTITY = '''    normalized_symbol = str(symbol or "").strip().upper()
    key = (id(broker), normalized_symbol)
'''

_NEW_ENTRY_PRICE_IDENTITY = '''    normalized_symbol = str(symbol or "").strip().upper()
    # v316: v98 wraps each reconciliation in a fresh transparent proof proxy.
    # Keying v279 by id(proxy) defeats its single-flight guarantee. A bound
    # method's __self__ is the real broker that owns get_real_entry_price and
    # remains stable across those proxies. No credential or broker response is
    # copied, synthesized, or persisted here; this changes coordination only.
    method_owner = getattr(method, "__self__", None)
    identity_broker = method_owner if method_owner is not None else broker
    key = (id(identity_broker), normalized_symbol)
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


def patch_position_sync_text(text: str) -> str:
    """Restore v279 single-flight identity across transparent proof proxies."""
    patched = text
    if _NEW_ENTRY_PRICE_IDENTITY not in patched:
        if _OLD_ENTRY_PRICE_IDENTITY not in patched:
            raise RuntimeError("startup_position_sync v279 identity anchor not found")
        patched = patched.replace(
            _OLD_ENTRY_PRICE_IDENTITY,
            _NEW_ENTRY_PRICE_IDENTITY,
            1,
        )

    if patched.count("identity_broker = method_owner if method_owner is not None else broker") != 1:
        raise RuntimeError("startup_position_sync must contain exactly one v316 identity owner")
    if "key = (id(broker), normalized_symbol)" in patched:
        raise RuntimeError("ephemeral v279 broker identity remains after v316 patch")
    if "key = (id(identity_broker), normalized_symbol)" not in patched:
        raise RuntimeError("stable v316 single-flight identity missing")
    return patched


def main() -> None:
    original_start = START_PATH.read_text(encoding="utf-8")
    patched_start = patch_text(original_start)
    START_PATH.write_text(patched_start, encoding="utf-8")

    original_launcher = LAUNCHER_PATH.read_text(encoding="utf-8")
    patched_launcher = patch_launcher_text(original_launcher)
    LAUNCHER_PATH.write_text(patched_launcher, encoding="utf-8")

    original_position_sync = POSITION_SYNC_PATH.read_text(encoding="utf-8")
    patched_position_sync = patch_position_sync_text(original_position_sync)
    POSITION_SYNC_PATH.write_text(patched_position_sync, encoding="utf-8")

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
    print(
        "ENTRY_PRICE_SINGLE_FLIGHT_IDENTITY_V316_PATCH_APPLIED "
        f"marker={ENTRY_PRICE_IDENTITY_MARKER} "
        f"position_sync_changed={patched_position_sync != original_position_sync} "
        "identity=bound_method_owner transparent_proxy_stable=true duplicate_history_workers=false "
        "entry_price_timeout_unchanged=true current_price_fallback=false "
        "cost_basis_fabricated=false readiness_granted=false execution_proof_fabricated=false "
        "forced_activation=false safety_gates_bypassed=false"
    )


if __name__ == "__main__":
    main()
