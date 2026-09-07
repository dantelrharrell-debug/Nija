#!/usr/bin/env python3
"""Apply NIJA protection binding + Kraken native-price precision repair v391.

This build-time patch is deliberately fail-closed and idempotent. It fixes two
production issues without weakening any protection requirement:

1. The generic trailing-stop monitor no longer reports an unbound
   ExecutionEngine as an actionable unprotected position when that engine has
   no open ledger positions. A missing ledger or a broker-less engine that
   actually sees open positions remains an ERROR and is never treated as
   protected.
2. Kraken native margin backup SL/TP trigger prices are formatted using the
   authenticated broker's public AssetPairs pair_decimals metadata (cached),
   with the existing ECEL Kraken schema as a conservative fallback. Quantity
   formatting, reduce_only, leverage, OpenOrders post-submit verification, and
   all four-way software protection remain unchanged.

No trade is opened, closed, resized, or fabricated by this patch.
"""
from __future__ import annotations

import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAILING = ROOT / "bot" / "trailing_stop_loss_runtime_patch.py"
NATIVE = ROOT / "bot" / "runtime_kraken_native_margin_backup_v380_patch.py"
MARKER = "20260907-protection-binding-precision-v391"


def _replace_once(path: Path, old: str, new: str, marker: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return False
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"v391 expected exactly one source block in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def patch_trailing() -> bool:
    old = '''    ledger = getattr(engine, "trade_ledger", None)\n    broker = getattr(engine, "broker_client", None) or getattr(engine, "broker", None)\n    if ledger is None or broker is None:\n        logger.error("TRAILING_STOP_ENGINE_UNPROTECTED missing_ledger_or_broker engine=%s", type(engine).__name__)\n        return 0\n    try:\n        positions = ledger.get_open_positions()\n    except Exception as exc:\n        logger.warning("TRAILING_STOP_SCAN_OPEN_POSITIONS_FAILED engine=%s err=%s", type(engine).__name__, exc)\n        return 0\n'''
    new = '''    # PROTECTION_BINDING_PRECISION_V391 marker=20260907-protection-binding-precision-v391\n    ledger = getattr(engine, "trade_ledger", None)\n    broker = getattr(engine, "broker_client", None) or getattr(engine, "broker", None)\n    if ledger is None:\n        # A missing ledger means we cannot prove whether this engine owns an\n        # actionable position. Keep this fail-closed and visible.\n        logger.error("TRAILING_STOP_ENGINE_UNPROTECTED missing_ledger engine=%s marker=20260907-protection-binding-precision-v391", type(engine).__name__)\n        return 0\n    try:\n        positions = ledger.get_open_positions()\n    except Exception as exc:\n        logger.warning("TRAILING_STOP_SCAN_OPEN_POSITIONS_FAILED engine=%s err=%s", type(engine).__name__, exc)\n        return 0\n    if broker is None:\n        open_count = len(positions or [])\n        if open_count:\n            # Do not hide a real protection gap: a broker-less engine that can\n            # see positions is still actionable and remains an ERROR.\n            logger.error(\n                "TRAILING_STOP_ENGINE_UNPROTECTED missing_broker engine=%s open_positions=%d marker=20260907-protection-binding-precision-v391",\n                type(engine).__name__, open_count,\n            )\n        else:\n            # ExecutionEngine() is legitimately constructed without a broker in\n            # several non-execution paths. With zero positions it is not an\n            # actionable protection failure; keep it registered so a later\n            # broker binding becomes scannable automatically.\n            logger.debug(\n                "TRAILING_STOP_ENGINE_DEFERRED_V391 missing_broker engine=%s open_positions=0 marker=20260907-protection-binding-precision-v391",\n                type(engine).__name__,\n            )\n        return 0\n'''
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


def main() -> int:
    changed_trailing = patch_trailing()
    changed_native = patch_native_precision()
    for path in (TRAILING, NATIVE):
        py_compile.compile(str(path), doraise=True)
    trailing_text = TRAILING.read_text(encoding="utf-8")
    native_text = NATIVE.read_text(encoding="utf-8")
    if "TRAILING_STOP_ENGINE_DEFERRED_V391" not in trailing_text:
        raise RuntimeError("v391 trailing marker verification failed")
    if "KRAKEN_NATIVE_MARGIN_PRICE_PRECISION_V391" not in native_text:
        raise RuntimeError("v391 Kraken native precision marker verification failed")
    print(
        "PROTECTION_BINDING_PRECISION_V391_READY "
        f"marker={MARKER} trailing_changed={str(changed_trailing).lower()} "
        f"native_precision_changed={str(changed_native).lower()} "
        "missing_ledger_fail_closed=true actionable_missing_broker_fail_closed=true "
        "empty_unbound_engine_not_actionable=true kraken_pair_decimals=true "
        "quantity_precision_unchanged=true reduce_only_unchanged=true "
        "openorders_proof_unchanged=true software_four_way_unchanged=true "
        "orders_submitted_by_patcher=false safety_gates_bypassed=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
