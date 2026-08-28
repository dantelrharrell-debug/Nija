"""Canonicalize Kraken legacy REST pair ids before ECEL contract lookup v206.

Production on deployment dff2273cb411da51f4f621eaaaae39783c38c24c
proved the heartbeat reached the real ExecutionPipeline and passed the heartbeat
safety gate plus pre-trade exposure checks, but ECEL rejected Kraken's native
``XETHZUSD`` pair id as ``XETHZ-USD`` with ``NO_CONTRACT_RULE``.  ECEL's Kraken
schema is keyed by canonical symbols such as ``ETH-USD`` and ``XBT-USD``.

v206 repairs only this symbol-identity boundary.  It translates the legacy
Kraken ids used by the heartbeat candidates into the existing canonical ECEL
symbols before the unchanged compiler performs contract lookup.  Unknown pair
ids continue through the previous normalizer and remain fail closed if no rule
exists.

V261 extends the same proven identity repair to the terminal Kraken broker
boundary after production showed ECEL accepted ``XETHZUSD`` but broker-local
normalization later synthesized invalid ``XETHZ-USD`` before Kraken submission.

No contract rule is invented, no minimum is reduced, and no execution, writer,
nonce, risk, kill-switch, capital, reconciliation, order or fill gate is
bypassed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any, Callable, Optional

LOGGER = logging.getLogger("nija.runtime_kraken_ecel_symbol_canonicalization_v206")
MARKER = "20260824-kraken-ecel-symbol-canonicalization-v206"
_READY_FLAG = "NIJA_KRAKEN_ECEL_SYMBOL_CANONICALIZATION_V206_READY"
_PATCH_ATTR = "_nija_kraken_ecel_symbol_canonicalization_v206"
_LOCK = threading.RLock()

_KRAKEN_BASE_ALIASES = {
    "XXBT": "XBT",
    "XBT": "XBT",
    "XETH": "ETH",
    "ETH": "ETH",
    "XXRP": "XRP",
    "XRP": "XRP",
}


def _legacy_kraken_pair(raw_symbol: str, broker: str) -> Optional[str]:
    if (broker or "").strip().lower() != "kraken":
        return None

    raw = (raw_symbol or "").strip().upper()
    if not raw or "-" in raw or "/" in raw:
        return None

    for raw_quote, canonical_quote in (("ZUSD", "USD"), ("USD", "USD")):
        if not raw.endswith(raw_quote) or len(raw) <= len(raw_quote):
            continue
        raw_base = raw[: -len(raw_quote)]
        canonical_base = _KRAKEN_BASE_ALIASES.get(raw_base)
        if canonical_base:
            return f"{canonical_base}-{canonical_quote}"
    return None


def _install_on_module(module: Any) -> bool:
    compiler_cls = getattr(module, "ECELExecutionCompiler", None)
    if compiler_cls is None:
        return False

    current = getattr(compiler_cls, "_normalize_symbol", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    previous: Callable[[str, str], str] = current

    @wraps(previous)
    def normalize_symbol(raw_symbol: str, broker: str) -> str:
        canonical = _legacy_kraken_pair(raw_symbol, broker)
        if canonical is not None:
            prior = previous(raw_symbol, broker)
            if prior != canonical:
                LOGGER.info(
                    "KRAKEN_ECEL_SYMBOL_V206_CANONICALIZED marker=%s raw=%s prior=%s canonical=%s contract_rules_unchanged=true",
                    MARKER,
                    raw_symbol,
                    prior,
                    canonical,
                )
            return canonical
        return previous(raw_symbol, broker)

    setattr(normalize_symbol, _PATCH_ATTR, True)
    setattr(normalize_symbol, "__wrapped__", previous)
    compiler_cls._normalize_symbol = staticmethod(normalize_symbol)
    return bool(getattr(compiler_cls._normalize_symbol, _PATCH_ATTR, False))


def _self_test(module: Any) -> bool:
    compiler_cls = getattr(module, "ECELExecutionCompiler", None)
    schema_cls = getattr(module, "ContractSchemaMap", None)
    if compiler_cls is None or schema_cls is None:
        return False

    normalize = getattr(compiler_cls, "_normalize_symbol", None)
    if not callable(normalize):
        return False

    cases = {
        "XETHZUSD": "ETH-USD",
        "XXBTZUSD": "XBT-USD",
        "XXRPZUSD": "XRP-USD",
        "SOLUSD": "SOL-USD",
        "BTC-USD": "BTC-USD",
    }
    for raw, expected in cases.items():
        if normalize(raw, "kraken") != expected:
            return False

    schema = schema_cls()
    for raw in ("XETHZUSD", "XXBTZUSD", "XXRPZUSD", "SOLUSD"):
        canonical = normalize(raw, "kraken")
        if schema.get_rule("kraken", canonical) is None:
            return False
    return True


def _install_v261() -> bool:
    try:
        module = importlib.import_module("bot.runtime_kraken_terminal_symbol_canonicalization_v261_patch")
        installer = getattr(module, "install", None)
        ready = bool(callable(installer) and installer())
        if not ready:
            LOGGER.critical(
                "KRAKEN_ECEL_SYMBOL_V206_V261_FAILED marker=%s trading_fail_closed=true",
                MARKER,
            )
        return ready
    except Exception as exc:
        LOGGER.critical(
            "KRAKEN_ECEL_SYMBOL_V206_V261_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def install() -> bool:
    with _LOCK:
        try:
            module = importlib.import_module("bot.ecel_execution_compiler")
        except Exception as exc:
            os.environ[_READY_FLAG] = "0"
            LOGGER.critical(
                "KRAKEN_ECEL_SYMBOL_V206_FAILED marker=%s reason=ecel_import_failed error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False

        installed = _install_on_module(module)
        tested = bool(installed and _self_test(module))
        v261_ready = bool(tested and _install_v261())
        ready = bool(installed and tested and v261_ready)
        os.environ[_READY_FLAG] = "1" if ready else "0"

        if not ready:
            LOGGER.critical(
                "KRAKEN_ECEL_SYMBOL_V206_FAILED marker=%s installed=%s self_test=%s v261_ready=%s trading_fail_closed=true",
                MARKER,
                str(installed).lower(),
                str(tested).lower(),
                str(v261_ready).lower(),
            )
            return False

        LOGGER.critical(
            "KRAKEN_ECEL_SYMBOL_V206_READY marker=%s ready=true legacy_xethzusd_to_ethusd=true "
            "legacy_xxbtzusd_to_xbtusd=true legacy_xxrpzusd_to_xrpusd=true existing_contract_rules_only=true "
            "terminal_symbol_v261=true contract_minimums_unchanged=true execution_authority_granted=false "
            "execution_proof_fabricated=false forced_trade=false "
            "writer_nonce_risk_killswitch_capital_position_order_fill_gates_unchanged=true safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_legacy_kraken_pair",
]
