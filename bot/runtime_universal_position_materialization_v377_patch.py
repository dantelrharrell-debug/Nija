"""Universal local-position materialization convergence v377.

NIJA's canonical PositionTracker.get_all_positions() returns symbol identifiers,
while the universal broker exit supervisor also supports trackers that return
full position rows. v377 bridges those two valid local interfaces so every
registered broker can present held positions to the same four-way protection
stack.

This patch performs local tracker reads only. It does not call broker/exchange
position APIs, prices, or order endpoints and never invents quantity, entry
price, side, or account identity.
"""
from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_universal_position_materialization_v377")
MARKER = "20260906-universal-position-materialization-v377"
_READY_FLAG = "NIJA_RUNTIME_UNIVERSAL_POSITION_MATERIALIZATION_V377_READY"
_PATCH_ATTR = "_nija_universal_position_materialization_v377"


def _row_signature(auto_exit: Any, row: Mapping[str, Any]) -> str:
    symbol = str(auto_exit._sym(row.get("symbol")) or "")
    pid = str(row.get("position_id") or "")
    qty = float(auto_exit._quantity(dict(row)) or 0.0)
    return f"{symbol}:{pid}:{qty:.12f}"


def _normalize(auto_exit: Any, broker: Any, raw: Any, symbol_hint: Any = "") -> dict[str, Any] | None:
    if isinstance(raw, Mapping):
        row = dict(raw)
    else:
        row = dict(getattr(raw, "__dict__", {}) or {})
    symbol = auto_exit._sym(row.get("symbol") or symbol_hint)
    qty = auto_exit._quantity(row)
    if not symbol or qty <= 0:
        return None
    row["symbol"] = symbol
    if not row.get("account_id"):
        account = "platform"
        for name in ("account_id", "account_name", "user_id", "username", "label", "name"):
            value = getattr(broker, name, None)
            if value:
                account = str(value)
                break
        row["account_id"] = account
    return row


def _local_tracker_rows(broker: Any) -> list[dict[str, Any]]:
    """Materialize local tracker rows without broker/exchange I/O."""
    tracker = getattr(broker, "position_tracker", None)
    if tracker is None:
        return []
    auto_exit = importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
    result: list[dict[str, Any]] = []

    for method_name in ("get_open_positions", "list_positions"):
        method = getattr(tracker, method_name, None)
        if not callable(method):
            continue
        try:
            raw = method()
        except Exception:
            continue
        if isinstance(raw, Mapping):
            items = list(raw.items())
            for key, value in items:
                row = _normalize(auto_exit, broker, value, key)
                if row is not None:
                    result.append(row)
        elif isinstance(raw, (list, tuple, set)):
            for value in raw:
                row = _normalize(auto_exit, broker, value)
                if row is not None:
                    result.append(row)
        if result:
            return result

    get_all = getattr(tracker, "get_all_positions", None)
    get_one = getattr(tracker, "get_position", None)
    if not callable(get_all):
        return result
    try:
        raw = get_all()
    except Exception:
        return result

    if isinstance(raw, Mapping):
        for key, value in raw.items():
            row = _normalize(auto_exit, broker, value, key)
            if row is not None:
                result.append(row)
        return result

    if not isinstance(raw, (list, tuple, set)):
        try:
            raw = tuple(raw)
        except Exception:
            return result

    for value in raw:
        if isinstance(value, Mapping) or getattr(value, "__dict__", None):
            row = _normalize(auto_exit, broker, value)
        elif callable(get_one):
            try:
                detail = get_one(value)
            except Exception:
                continue
            row = _normalize(auto_exit, broker, detail, value)
        else:
            row = None
        if row is not None:
            result.append(row)
    return result


def _patch_supervisor() -> bool:
    supervisor = importlib.import_module("bot.universal_broker_exit_supervisor_patch")
    current = getattr(supervisor, "_tracker_positions", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        os.environ[_READY_FLAG] = "1"
        return True

    @wraps(current)
    def tracker_positions_v377(broker: Any) -> list[dict[str, Any]]:
        auto_exit = importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
        try:
            existing = current(broker)
        except Exception:
            existing = []
        output: list[dict[str, Any]] = [
            dict(row) for row in list(existing or []) if isinstance(row, Mapping)
        ]
        seen = {_row_signature(auto_exit, row) for row in output}
        for row in _local_tracker_rows(broker):
            signature = _row_signature(auto_exit, row)
            if signature in seen:
                continue
            seen.add(signature)
            output.append(row)
        return output

    setattr(tracker_positions_v377, _PATCH_ATTR, True)
    setattr(tracker_positions_v377, "__wrapped__", current)
    supervisor._tracker_positions = tracker_positions_v377
    os.environ[_READY_FLAG] = "1"
    LOGGER.critical(
        "RUNTIME_UNIVERSAL_POSITION_MATERIALIZATION_V377_READY marker=%s "
        "symbol_only_trackers_supported=true local_tracker_reads_only=true broker_io=false "
        "position_fabricated=false safety_gates_bypassed=false",
        MARKER,
    )
    return True


def install_import_hook() -> bool:
    try:
        ready = _patch_supervisor()
    except Exception as exc:
        os.environ[_READY_FLAG] = "0"
        LOGGER.exception(
            "RUNTIME_UNIVERSAL_POSITION_MATERIALIZATION_V377_FAILED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False
    os.environ[_READY_FLAG] = "1" if ready else "0"
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook", "_local_tracker_rows", "_patch_supervisor"]
