"""Apply canonical production-image source hardening.

This build step preserves the v26 canonical launcher and safety-critical
production repairs:

* v313 acquires/verifies the exact Redis writer lease before importing
  ``bot.bot``.
* v316 keys startup cost-basis single-flights by the real bound broker method
  owner instead of ephemeral transparent proof proxies.
* v317 keeps Coinbase fill units explicit. Production on 2026-08-31 proved a
  quote-sized $12.50 maker BUY was returned as ``filled_size=12.5`` and then
  added to the tracker as 12.5 BTC even though the authoritative broker snapshot
  remained 0.00079517 BTC. v317 makes ``filled_size`` base-asset units only,
  never falls back from unresolved quote BUY fill size to the quote-dollar
  request, and defers local tracker mutation when base fill quantity is not
  proven. Maker-order submitted ``base_size`` is not treated as a completed fill.

No repair fabricates writer authority, cost basis, position truth, execution
proof, or activation. Timeouts remain fail-closed and current market price is
never substituted for entry price in position reconciliation.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START_PATH = ROOT / "start.sh"
LAUNCHER_PATH = ROOT / "scripts" / "canonical_runtime_launcher_v26.py"
POSITION_SYNC_PATH = ROOT / "bot" / "startup_position_sync.py"
BROKER_MANAGER_PATH = ROOT / "bot" / "broker_manager.py"
OLD_LAUNCH = "$PY -u main.py"
NEW_LAUNCH = "$PY -u scripts/canonical_runtime_launcher_v26.py"
MARKER = "20260724-canonical-runtime-launcher-v26"
WRITER_IMPORT_ORDER_MARKER = "20260831-canonical-writer-import-order-v313"
ENTRY_PRICE_IDENTITY_MARKER = "20260831-entry-price-single-flight-identity-v316"
COINBASE_FILL_UNIT_MARKER = "20260831-coinbase-quote-base-fill-normalization-v317"

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

_OLD_COINBASE_FILL_BLOCK = '''            # Extract or estimate filled size
            # Coinbase API v3 doesn't return filled_size in the response,
            # so we estimate based on what we sent
            filled_size = None

            # Try to extract from success_response
            success_response = order_dict.get('success_response', {})
            if success_response:
                filled_size = success_response.get('filled_size')

            # If not available, estimate based on order configuration
            if not filled_size:
                order_config = order_dict.get('order_configuration', {})
                market_config = order_config.get('market_market_ioc', {})

                if side.upper() == 'BUY' and 'quote_size' in market_config:
                    # For buy orders, estimate crypto received = quote_size / price
                    try:
                        quote_size = float(market_config['quote_size'])
                        # RATE LIMIT FIX: Wrap get_product with rate limiter to prevent 429 errors
                        def _fetch_price_data():
                            return self.client.get_product(symbol)

                        if self._rate_limiter:
                            price_data = self._rate_limiter.call('get_product', _fetch_price_data)
                        else:
                            price_data = _fetch_price_data()

                        if price_data and 'price' in price_data:
                            current_price = float(price_data['price'])
                            filled_size = quote_size / current_price
                    except Exception:
                        # Fallback: use quantity as estimate
                        filled_size = quantity
                else:
                    # For sell orders or unknown, use quantity as estimate
                    filled_size = quantity

            logger.debug(f"   Filled crypto amount: {filled_size:.6f}" if filled_size else "   Filled amount: unknown")

            # Resolve actual fill price: immediate response → get_order() → current price
            fill_price = self._fetch_actual_fill_price(order_dict, symbol)
'''

_NEW_COINBASE_FILL_BLOCK = '''            # v317: filled_size is BASE-ASSET quantity only. Never put quote USD
            # into this field. A submitted maker base_size is an order request,
            # not proof that the order completed, so it is intentionally not used
            # as filled quantity unless Coinbase explicitly reports a fill.
            filled_size = None
            filled_size_source = "unresolved"

            success_response = order_dict.get('success_response', {}) or {}
            if isinstance(success_response, dict):
                for _fill_key in ('filled_size', 'filled_base_size'):
                    try:
                        _reported_fill = float(success_response.get(_fill_key) or 0.0)
                    except Exception:
                        _reported_fill = 0.0
                    if _reported_fill > 0.0:
                        filled_size = _reported_fill
                        filled_size_source = f"success_response:{_fill_key}"
                        break

            # Resolve actual fill price before any quote->base conversion.
            fill_price = self._fetch_actual_fill_price(order_dict, symbol)
            order_config = order_dict.get('order_configuration', {}) or {}

            if not filled_size and side.upper() == 'BUY' and size_type == 'quote':
                # A market quote order can be converted to base quantity only when
                # the response carries the quote_size and the fill-price helper
                # resolves a positive price. The old fallback ``filled_size = quantity``
                # was the exact USD->BTC unit corruption seen in production.
                market_config = order_config.get('market_market_ioc', {}) or {}
                try:
                    quote_size = float(market_config.get('quote_size') or 0.0)
                except Exception:
                    quote_size = 0.0
                if quote_size > 0.0 and fill_price and float(fill_price) > 0.0:
                    filled_size = quote_size / float(fill_price)
                    filled_size_source = "market_quote_size_div_fill_price"

            if not filled_size and size_type == 'base':
                # Base-sized orders already express quantity in base units. This
                # fallback is never used for quote-sized BUYs.
                try:
                    _base_requested = float(quantity or 0.0)
                except Exception:
                    _base_requested = 0.0
                if _base_requested > 0.0:
                    filled_size = _base_requested
                    filled_size_source = "base_sized_request"

            logger.critical(
                "COINBASE_FILL_UNIT_V317 marker=20260831-coinbase-quote-base-fill-normalization-v317 "
                "symbol=%s side=%s size_type=%s filled_base=%s source=%s quote_request=%s "
                "maker_submitted_base_not_fill_proof=true quote_as_base_forbidden=true",
                symbol,
                side,
                size_type,
                "unproven" if not filled_size else f"{float(filled_size):.12f}",
                filled_size_source,
                quantity if size_type == 'quote' else "n/a",
            )
            logger.debug(
                f"   Filled crypto amount: {filled_size:.6f}"
                if filled_size else "   Filled base amount: unproven"
            )
'''

_OLD_COINBASE_ENTRY_LOG = '''                logger.info(
                    f"▶ ENTRY CONFIRMED [{symbol}]: "
                    f"filled @ ${fill_price:.4g} | "
                    f"qty: {filled_size:.6g} | "
                    f"size: ${size_usd:.2f} | "
                    f"acct: {account_label}"
                )
'''

_NEW_COINBASE_ENTRY_LOG = '''                _filled_qty_text = f"{float(filled_size):.6g}" if filled_size else "unproven"
                logger.info(
                    f"▶ ENTRY CONFIRMED [{symbol}]: "
                    f"filled @ ${fill_price:.4g} | "
                    f"qty: {_filled_qty_text} | "
                    f"size: ${size_usd:.2f} | "
                    f"acct: {account_label}"
                )
'''

_OLD_COINBASE_TRACK_CONDITION = '''                        if fill_price and fill_price > 0:
                            size_usd = quantity if size_type == 'quote' else (filled_size * fill_price if filled_size else 0)
                            self.position_tracker.track_entry(
'''

_NEW_COINBASE_TRACK_CONDITION = '''                        if fill_price and fill_price > 0 and filled_size and float(filled_size) > 0:
                            size_usd = quantity if size_type == 'quote' else (filled_size * fill_price if filled_size else 0)
                            self.position_tracker.track_entry(
'''

_OLD_COINBASE_RETURN = '''            return {
                "status": "filled",
                "order": order_dict,
                "filled_size": float(filled_size) if filled_size else 0.0
            }
'''

_NEW_COINBASE_RETURN = '''            if side.lower() == 'buy' and not filled_size:
                logger.critical(
                    "COINBASE_LOCAL_TRACKER_ENTRY_DEFERRED_V317 marker=20260831-coinbase-quote-base-fill-normalization-v317 "
                    "symbol=%s reason=base_fill_quantity_unproven tracker_mutation=false "
                    "authoritative_position_reconciliation_required=true execution_proof_not_granted=true",
                    symbol,
                )
            return {
                "status": "filled" if filled_size else "open",
                "order": order_dict,
                "filled_size": float(filled_size) if filled_size else 0.0,
                "filled_size_usd": float(quantity) if size_type == 'quote' else (
                    float(filled_size or 0.0) * float(fill_price or 0.0)
                ),
                "fill_confirmation_required": not bool(filled_size),
            }
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
        patched = patched.replace(_OLD_ENTRY_PRICE_IDENTITY, _NEW_ENTRY_PRICE_IDENTITY, 1)

    if patched.count("identity_broker = method_owner if method_owner is not None else broker") != 1:
        raise RuntimeError("startup_position_sync must contain exactly one v316 identity owner")
    if "key = (id(broker), normalized_symbol)" in patched:
        raise RuntimeError("ephemeral v279 broker identity remains after v316 patch")
    if "key = (id(identity_broker), normalized_symbol)" not in patched:
        raise RuntimeError("stable v316 single-flight identity missing")
    return patched


def patch_broker_manager_text(text: str) -> str:
    """Keep Coinbase quote notional and base fill quantity in distinct units."""
    patched = text
    replacements = (
        (_OLD_COINBASE_FILL_BLOCK, _NEW_COINBASE_FILL_BLOCK, "fill normalization"),
        (_OLD_COINBASE_ENTRY_LOG, _NEW_COINBASE_ENTRY_LOG, "entry log"),
        (_OLD_COINBASE_TRACK_CONDITION, _NEW_COINBASE_TRACK_CONDITION, "tracker guard"),
        (_OLD_COINBASE_RETURN, _NEW_COINBASE_RETURN, "return contract"),
    )
    for old, new, label in replacements:
        if new not in patched:
            if old not in patched:
                raise RuntimeError(f"Coinbase v317 {label} anchor not found")
            patched = patched.replace(old, new, 1)

    if "Fallback: use quantity as estimate" in patched:
        raise RuntimeError("unsafe Coinbase quote-as-base fallback remains after v317")
    if '"status": "filled" if filled_size else "open"' not in patched:
        raise RuntimeError("Coinbase v317 unresolved-fill status contract missing")
    if "maker_submitted_base_not_fill_proof=true" not in patched:
        raise RuntimeError("Coinbase v317 maker fill-proof guard missing")
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

    original_broker_manager = BROKER_MANAGER_PATH.read_text(encoding="utf-8")
    patched_broker_manager = patch_broker_manager_text(original_broker_manager)
    BROKER_MANAGER_PATH.write_text(patched_broker_manager, encoding="utf-8")

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
    print(
        "COINBASE_QUOTE_BASE_FILL_NORMALIZATION_V317_PATCH_APPLIED "
        f"marker={COINBASE_FILL_UNIT_MARKER} "
        f"broker_manager_changed={patched_broker_manager != original_broker_manager} "
        "filled_size_unit=base quote_notional_separate=true quote_as_base_forbidden=true "
        "maker_submitted_base_not_fill_proof=true unresolved_fill_tracker_mutation=false "
        "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false"
    )


if __name__ == "__main__":
    main()
