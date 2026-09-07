#!/usr/bin/env python3
"""Apply NIJA protection binding + Kraken native-order repair v391/v392.

This build-time patch is deliberately fail-closed and idempotent. It fixes
production protection issues without weakening any protection requirement:

1. The generic trailing-stop monitor no longer reports a fully unbound,
   position-incapable ExecutionEngine as an actionable unprotected position.
2. A broker-bound ExecutionEngine created before the trade-ledger DB becomes
   available can late-bind the canonical ledger on a later protection scan.
3. Kraken native margin backup SL/TP trigger prices are formatted using the
   authenticated broker's public AssetPairs pair_decimals metadata (cached),
   with the existing ECEL Kraken schema as a conservative fallback.
4. Kraken ``cl_ord_id not unique`` is recovered without blind duplicate-order
   submission: OpenOrders is re-proved first; an existing matching client ID is
   adopted for post-submit proof, otherwise one scoped collision ID is rotated
   and retried. Rotated NIJA IDs remain eligible for orphan cleanup.

Quantity formatting, reduce_only, leverage, authenticated OpenPositions,
OpenOrders post-submit verification, and all four-way software protection stay
fail-closed. No trade is opened, closed, resized, or fabricated by this patch.
"""
from __future__ import annotations

import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAILING = ROOT / "bot" / "trailing_stop_loss_runtime_patch.py"
NATIVE = ROOT / "bot" / "runtime_kraken_native_margin_backup_v380_patch.py"
MARKER = "20260907-protection-binding-precision-v391"
RECOVERY_MARKER = "20260907-kraken-client-id-ledger-rebind-v392"


def _replace_once(path: Path, old: str, new: str, marker: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return False
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"v391/v392 expected exactly one source block in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def patch_trailing() -> bool:
    old = '''    ledger = getattr(engine, "trade_ledger", None)\n    broker = getattr(engine, "broker_client", None) or getattr(engine, "broker", None)\n    if ledger is None or broker is None:\n        logger.error("TRAILING_STOP_ENGINE_UNPROTECTED missing_ledger_or_broker engine=%s", type(engine).__name__)\n        return 0\n    try:\n        positions = ledger.get_open_positions()\n    except Exception as exc:\n        logger.warning("TRAILING_STOP_SCAN_OPEN_POSITIONS_FAILED engine=%s err=%s", type(engine).__name__, exc)\n        return 0\n'''
    new = '''    # PROTECTION_BINDING_PRECISION_V391 marker=20260907-protection-binding-precision-v391\n    # KRAKEN_CLIENT_ID_LEDGER_REBIND_V392 marker=20260907-kraken-client-id-ledger-rebind-v392\n    ledger = getattr(engine, "trade_ledger", None)\n    broker = getattr(engine, "broker_client", None) or getattr(engine, "broker", None)\n    if ledger is None and broker is not None:\n        # ExecutionEngine instances can be constructed before the ledger module\n        # finishes initializing during Render startup. Rebind only to the\n        # canonical ledger factory; never synthesize a ledger or position.\n        factory = None\n        try:\n            from bot.trade_ledger_db import get_trade_ledger_db as factory\n        except Exception:\n            try:\n                from trade_ledger_db import get_trade_ledger_db as factory\n            except Exception:\n                factory = None\n        if callable(factory):\n            try:\n                candidate = factory()\n                if candidate is not None and callable(getattr(candidate, "get_open_positions", None)):\n                    setattr(engine, "trade_ledger", candidate)\n                    ledger = candidate\n                    logger.critical(\n                        "TRAILING_STOP_ENGINE_LEDGER_REBOUND_V392 engine=%s broker_bound=true "\n                        "canonical_factory=true synthetic_ledger=false marker=20260907-kraken-client-id-ledger-rebind-v392",\n                        type(engine).__name__,\n                    )\n            except Exception as exc:\n                logger.warning(\n                    "TRAILING_STOP_ENGINE_LEDGER_REBIND_FAILED_V392 engine=%s err=%s "\n                    "marker=20260907-kraken-client-id-ledger-rebind-v392",\n                    type(engine).__name__, exc,\n                )\n    if ledger is None:\n        if broker is None:\n            # A completely unbound ExecutionEngine cannot own or execute an\n            # actionable position. Keep it registered for a later binding, but\n            # do not emit a false protection failure while it is inert.\n            logger.debug(\n                "TRAILING_STOP_ENGINE_DEFERRED_V391 missing_ledger_and_broker engine=%s marker=20260907-protection-binding-precision-v391",\n                type(engine).__name__,\n            )\n        else:\n            # Broker-bound with no ledger is materially different: we cannot\n            # prove the broker's actionable positions are represented locally.\n            # Keep that state fail-closed and visible.\n            logger.error(\n                "TRAILING_STOP_ENGINE_UNPROTECTED missing_ledger broker_bound=true engine=%s marker=20260907-protection-binding-precision-v391",\n                type(engine).__name__,\n            )\n        return 0\n    try:\n        positions = ledger.get_open_positions()\n    except Exception as exc:\n        logger.warning("TRAILING_STOP_SCAN_OPEN_POSITIONS_FAILED engine=%s err=%s", type(engine).__name__, exc)\n        return 0\n    if broker is None:\n        open_count = len(positions or [])\n        if open_count:\n            # Do not hide a real protection gap: a broker-less engine that can\n            # see positions is still actionable and remains an ERROR.\n            logger.error(\n                "TRAILING_STOP_ENGINE_UNPROTECTED missing_broker engine=%s open_positions=%d marker=20260907-protection-binding-precision-v391",\n                type(engine).__name__, open_count,\n            )\n        else:\n            # ExecutionEngine() is legitimately constructed without a broker in\n            # several non-execution paths. With zero positions it is not an\n            # actionable protection failure; keep it registered so a later\n            # broker binding becomes scannable automatically.\n            logger.debug(\n                "TRAILING_STOP_ENGINE_DEFERRED_V391 missing_broker engine=%s open_positions=0 marker=20260907-protection-binding-precision-v391",\n                type(engine).__name__,\n            )\n        return 0\n'''
    return _replace_once(
        TRAILING, old, new,
        "PROTECTION_BINDING_PRECISION_V391 marker=20260907-protection-binding-precision-v391",
    )


def patch_native_precision() -> bool:
    text = NATIVE.read_text(encoding="utf-8")
    marker = "KRAKEN_NATIVE_MARGIN_PRICE_PRECISION_V391"
    if marker in text:
        return False

    old_globals = '''_EPS = 1e-12\n_TRUE = {"1", "true", "yes", "on", "enabled", "y"}\n'''
    new_globals = '''_EPS = 1e-12\n# KRAKEN_NATIVE_MARGIN_PRICE_PRECISION_V391 marker=20260907-protection-binding-precision-v391\n_PAIR_PRICE_PRECISION_V391: dict[tuple[int, str], int] = {}\n_TRUE = {"1", "true", "yes", "on", "enabled", "y"}\n'''
    if text.count(old_globals) != 1:
        raise RuntimeError("v391 native precision globals anchor missing or ambiguous")
    text = text.replace(old_globals, new_globals, 1)

    old_fmt = '''def _fmt(value: float) -> str:\n    text = f"{float(value):.12f}".rstrip("0").rstrip(".")\n    return text or "0"\n\n\n'''
    new_fmt = '''def _fmt(value: float, decimals: int = 12) -> str:\n    places = max(0, min(12, int(decimals)))\n    text = f"{float(value):.{places}f}".rstrip("0").rstrip(".")\n    return text or "0"\n\n\ndef _pair_price_precision_v391(broker: Any, pair: str) -> int:\n    """Return Kraken pair_decimals without weakening order validation.\n\n    Public AssetPairs metadata is authoritative and cached by broker+pair. The\n    ECEL Kraken schema is used only when the public metadata read is unavailable.\n    A conservative 2-decimal fallback is last resort; Kraken will still reject\n    an invalid order and v380 will remain unverified rather than fabricate proof.\n    """\n    pair_key = str(pair or "").strip().upper()\n    key = (id(broker), pair_key)\n    cached = _PAIR_PRICE_PRECISION_V391.get(key)\n    if cached is not None:\n        return cached\n\n    precision: int | None = None\n    try:\n        public_call = getattr(_kraken_exit(), "_public_call", None)\n        if callable(public_call):\n            payload = public_call(broker, "AssetPairs", {"pair": pair_key})\n            result = payload.get("result", {}) if isinstance(payload, Mapping) else {}\n            if isinstance(result, Mapping):\n                for info in result.values():\n                    if not isinstance(info, Mapping):\n                        continue\n                    raw = info.get("pair_decimals")\n                    if raw is None:\n                        continue\n                    candidate = int(float(raw))\n                    if 0 <= candidate <= 12:\n                        precision = candidate\n                        break\n    except Exception as exc:\n        LOGGER.debug("KRAKEN_NATIVE_MARGIN_PRICE_PRECISION_V391_ASSETPAIRS_FAILED pair=%s err=%s", pair_key, exc)\n\n    if precision is None:\n        try:\n            from bot.ecel_execution_compiler import ContractSchemaMap\n            lookup = pair_key.replace("/", "").replace("-", "")\n            symbol = ""\n            for quote in ("USDC", "USD"):\n                if lookup.endswith(quote) and len(lookup) > len(quote):\n                    symbol = f"{lookup[:-len(quote)]}-{quote}"\n                    break\n            if symbol:\n                rule = ContractSchemaMap().get_rule("kraken", symbol)\n                candidate = getattr(rule, "price_precision", None) if rule is not None else None\n                if candidate is not None:\n                    candidate = int(candidate)\n                    if 0 <= candidate <= 12:\n                        precision = candidate\n        except Exception as exc:\n            LOGGER.debug("KRAKEN_NATIVE_MARGIN_PRICE_PRECISION_V391_ECEL_FAILED pair=%s err=%s", pair_key, exc)\n\n    if precision is None:\n        precision = 2\n    _PAIR_PRICE_PRECISION_V391[key] = precision\n    LOGGER.info(\n        "KRAKEN_NATIVE_MARGIN_PRICE_PRECISION_V391 pair=%s price_decimals=%d authoritative_or_schema=true marker=20260907-protection-binding-precision-v391",\n        pair_key, precision,\n    )\n    return precision\n\n\n'''
    if text.count(old_fmt) != 1:
        raise RuntimeError("v391 native _fmt anchor missing or ambiguous")
    text = text.replace(old_fmt, new_fmt, 1)

    old_params = '''    params: dict[str, Any] = {\n        "pair": pair,\n        "type": "sell",\n        "ordertype": ordertype,\n        "volume": _fmt(quantity),\n        "price": _fmt(trigger),\n        "reduce_only": True,\n    }\n'''
    new_params = '''    price_decimals = _pair_price_precision_v391(broker, pair)\n    params: dict[str, Any] = {\n        "pair": pair,\n        "type": "sell",\n        "ordertype": ordertype,\n        "volume": _fmt(quantity),\n        "price": _fmt(trigger, price_decimals),\n        "reduce_only": True,\n    }\n'''
    if text.count(old_params) != 1:
        raise RuntimeError("v391 native AddOrder params anchor missing or ambiguous")
    NATIVE.write_text(text.replace(old_params, new_params, 1), encoding="utf-8")
    return True


def patch_native_client_id_recovery() -> bool:
    text = NATIVE.read_text(encoding="utf-8")
    marker = "KRAKEN_NATIVE_MARGIN_CLIENT_ID_RECOVERY_V392"
    if marker in text:
        return False

    old_globals = '''_PREFIX_SL = "njsl"\n_PREFIX_TP = "njtp"\n'''
    new_globals = '''_PREFIX_SL = "njsl"\n_PREFIX_TP = "njtp"\n# KRAKEN_NATIVE_MARGIN_CLIENT_ID_RECOVERY_V392 marker=20260907-kraken-client-id-ledger-rebind-v392\n_CLIENT_ID_ROTATION_V392: dict[tuple[str, str, str], int] = {}\n_CLIENT_ID_SALT_V392 = hashlib.sha1(os.urandom(16)).hexdigest()[:7]\n'''
    if text.count(old_globals) != 1:
        raise RuntimeError("v392 native client-id globals anchor missing or ambiguous")
    text = text.replace(old_globals, new_globals, 1)

    old_client = '''def _client_id(account: str, symbol: str, leg: str) -> str:\n    digest = hashlib.sha1(f"{account}|{symbol}".encode("utf-8")).hexdigest()[:12]\n    prefix = _PREFIX_SL if leg == "stop-loss" else _PREFIX_TP\n    return f"{prefix}{digest}"[:18]\n\n\n'''
    new_client = '''def _client_id(account: str, symbol: str, leg: str) -> str:\n    digest = hashlib.sha1(f"{account}|{symbol}".encode("utf-8")).hexdigest()[:12]\n    prefix = _PREFIX_SL if leg == "stop-loss" else _PREFIX_TP\n    return f"{prefix}{digest}"[:18]\n\n\ndef _client_id_scope_v392(account: str, symbol: str, leg: str) -> str:\n    digest = hashlib.sha1(f"{account}|{symbol}".encode("utf-8")).hexdigest()[:7]\n    prefix = _PREFIX_SL if leg == "stop-loss" else _PREFIX_TP\n    return f"{prefix}{digest}"\n\n\ndef _rotated_client_id_v392(account: str, symbol: str, leg: str) -> str:\n    key = (str(account), str(symbol), str(leg))\n    with _LOCK:\n        counter = int(_CLIENT_ID_ROTATION_V392.get(key, 0)) + 1\n        _CLIENT_ID_ROTATION_V392[key] = counter\n    suffix = hashlib.sha1(f"{_CLIENT_ID_SALT_V392}|{counter}".encode("utf-8")).hexdigest()[:7]\n    return f"{_client_id_scope_v392(account, symbol, leg)}{suffix}"[:18]\n\n\ndef _client_id_open_v392(broker: Any, client_id: str) -> tuple[bool, tuple[str, ...], str]:\n    """Re-prove whether a colliding client ID is already an open Kraken order."""\n    try:\n        payload = _call(broker, "OpenOrders", {"trades": "false"}, "QUERY")\n    except Exception as exc:\n        return False, (), f"openorders_exception:{type(exc).__name__}:{exc}"\n    if not isinstance(payload, Mapping):\n        return False, (), "invalid_openorders_payload"\n    errors = payload.get("error") or []\n    if isinstance(errors, str):\n        errors = [errors]\n    if errors:\n        return False, (), "openorders_rejected:" + ",".join(str(item) for item in errors)\n    result = payload.get("result") or {}\n    opened = result.get("open", result) if isinstance(result, Mapping) else {}\n    if not isinstance(opened, Mapping):\n        return False, (), "invalid_openorders_open"\n    matches: list[str] = []\n    wanted = str(client_id or "").strip()\n    for order_id, raw in opened.items():\n        if not isinstance(raw, Mapping):\n            continue\n        seen = str(raw.get("cl_ord_id") or raw.get("cl_ordid") or "").strip()\n        if wanted and seen == wanted:\n            matches.append(str(order_id))\n    return True, tuple(sorted(matches)), "ok"\n\n\n'''
    if text.count(old_client) != 1:
        raise RuntimeError("v392 native _client_id anchor missing or ambiguous")
    text = text.replace(old_client, new_client, 1)

    old_tail = '''    if not txids:\n        return False, (), "addorder_ack_without_txid"\n    return True, txids, "ok"\n\n\ndef _row_targets(raw: Mapping[str, Any]) -> dict[str, Any]:\n'''
    new_tail = '''    if not txids:\n        return False, (), "addorder_ack_without_txid"\n    return True, txids, "ok"\n\n\ndef _submit_reduce_only_with_recovery_v392(\n    account: str,\n    symbol: str,\n    broker: Any,\n    *,\n    pair: str,\n    quantity: float,\n    leverage: int,\n    ordertype: str,\n    trigger: float,\n) -> tuple[bool, tuple[str, ...], str]:\n    """Submit one NIJA native protective leg with collision-safe recovery.\n\n    A duplicate client ID is never treated as permission to blindly add a\n    second protective order. OpenOrders is re-proved first. If the exact ID is\n    already open, its Kraken order ID is adopted and the caller's mandatory\n    post-submit coverage proof decides whether that order is actually valid. If\n    the exact ID is absent, a scoped rotated ID is submitted once.\n    """\n    primary_id = _client_id(account, symbol, ordertype)\n    ok, txids, reason = _submit_reduce_only(\n        broker, pair=pair, quantity=quantity, leverage=leverage,\n        ordertype=ordertype, trigger=trigger, client_id=primary_id,\n    )\n    if ok or "cl_ord_id not unique" not in str(reason).lower():\n        return ok, txids, reason\n\n    with _LOCK:\n        proven, existing_ids, probe_reason = _client_id_open_v392(broker, primary_id)\n        if not proven:\n            return False, (), f"client_id_collision_openorders_unproven:{probe_reason}"\n        if existing_ids:\n            LOGGER.warning(\n                "KRAKEN_NATIVE_MARGIN_CLIENT_ID_COLLISION_ADOPTED_V392 account=%s symbol=%s leg=%s "\n                "client_id=%s order_ids=%s post_submit_proof_required=true blind_duplicate_submit=false "\n                "marker=20260907-kraken-client-id-ledger-rebind-v392",\n                account, symbol, ordertype, primary_id, existing_ids,\n            )\n            return True, existing_ids, "client_id_collision_existing_open_order"\n\n        rotated_id = _rotated_client_id_v392(account, symbol, ordertype)\n        ok, txids, retry_reason = _submit_reduce_only(\n            broker, pair=pair, quantity=quantity, leverage=leverage,\n            ordertype=ordertype, trigger=trigger, client_id=rotated_id,\n        )\n        if ok:\n            LOGGER.critical(\n                "KRAKEN_NATIVE_MARGIN_CLIENT_ID_ROTATED_V392 account=%s symbol=%s leg=%s "\n                "old_client_id=%s new_client_id=%s order_ids=%s openorders_old_id_absent=true "\n                "post_submit_proof_required=true reduce_only_unchanged=true marker=20260907-kraken-client-id-ledger-rebind-v392",\n                account, symbol, ordertype, primary_id, rotated_id, txids,\n            )\n        return ok, txids, retry_reason\n\n\ndef _row_targets(raw: Mapping[str, Any]) -> dict[str, Any]:\n'''
    if text.count(old_tail) != 1:
        raise RuntimeError("v392 native submit helper anchor missing or ambiguous")
    text = text.replace(old_tail, new_tail, 1)

    old_stop = '''        ok, txids, reason = _submit_reduce_only(\n            broker, pair=pair, quantity=quantity, leverage=leverage,\n            ordertype="stop-loss", trigger=stop,\n            client_id=_client_id(account, symbol, "stop-loss"),\n        )\n'''
    new_stop = '''        ok, txids, reason = _submit_reduce_only_with_recovery_v392(\n            account, symbol, broker, pair=pair, quantity=quantity, leverage=leverage,\n            ordertype="stop-loss", trigger=stop,\n        )\n'''
    if text.count(old_stop) != 1:
        raise RuntimeError("v392 native stop submit anchor missing or ambiguous")
    text = text.replace(old_stop, new_stop, 1)

    old_tp = '''        ok, txids, reason = _submit_reduce_only(\n            broker, pair=pair, quantity=quantity, leverage=leverage,\n            ordertype="take-profit", trigger=tp,\n            client_id=_client_id(account, symbol, "take-profit"),\n        )\n'''
    new_tp = '''        ok, txids, reason = _submit_reduce_only_with_recovery_v392(\n            account, symbol, broker, pair=pair, quantity=quantity, leverage=leverage,\n            ordertype="take-profit", trigger=tp,\n        )\n'''
    if text.count(old_tp) != 1:
        raise RuntimeError("v392 native take-profit submit anchor missing or ambiguous")
    text = text.replace(old_tp, new_tp, 1)

    old_cleanup = '''        if client_id not in {\n            _client_id(account, symbol, "stop-loss"),\n            _client_id(account, symbol, "take-profit"),\n        }:\n            continue\n'''
    new_cleanup = '''        client_scopes = (\n            _client_id_scope_v392(account, symbol, "stop-loss"),\n            _client_id_scope_v392(account, symbol, "take-profit"),\n        )\n        if not any(client_id.startswith(scope) for scope in client_scopes):\n            continue\n'''
    if text.count(old_cleanup) != 1:
        raise RuntimeError("v392 native orphan cleanup anchor missing or ambiguous")
    NATIVE.write_text(text.replace(old_cleanup, new_cleanup, 1), encoding="utf-8")
    return True


def main() -> int:
    changed_trailing = patch_trailing()
    changed_native = patch_native_precision()
    changed_client_id = patch_native_client_id_recovery()
    for path in (TRAILING, NATIVE):
        py_compile.compile(str(path), doraise=True)
    trailing_text = TRAILING.read_text(encoding="utf-8")
    native_text = NATIVE.read_text(encoding="utf-8")
    if "TRAILING_STOP_ENGINE_DEFERRED_V391" not in trailing_text:
        raise RuntimeError("v391 trailing marker verification failed")
    if "TRAILING_STOP_ENGINE_LEDGER_REBOUND_V392" not in trailing_text:
        raise RuntimeError("v392 trailing ledger-rebind marker verification failed")
    if "KRAKEN_NATIVE_MARGIN_PRICE_PRECISION_V391" not in native_text:
        raise RuntimeError("v391 Kraken native precision marker verification failed")
    if "KRAKEN_NATIVE_MARGIN_CLIENT_ID_RECOVERY_V392" not in native_text:
        raise RuntimeError("v392 Kraken client-id recovery marker verification failed")
    print(
        "PROTECTION_BINDING_PRECISION_V391_READY "
        f"marker={MARKER} recovery_marker={RECOVERY_MARKER} "
        f"trailing_changed={str(changed_trailing).lower()} "
        f"native_precision_changed={str(changed_native).lower()} "
        f"client_id_recovery_changed={str(changed_client_id).lower()} "
        "broker_bound_missing_ledger_late_rebind=true actionable_missing_broker_fail_closed=true "
        "fully_unbound_engine_not_actionable=true kraken_pair_decimals=true "
        "client_id_collision_openorders_reproof=true client_id_rotation_after_absence_only=true "
        "rotated_id_orphan_cleanup=true quantity_precision_unchanged=true reduce_only_unchanged=true "
        "openorders_post_submit_proof_unchanged=true software_four_way_unchanged=true "
        "orders_submitted_by_patcher=false safety_gates_bypassed=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
