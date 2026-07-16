"""Final account isolation and exit-integrity guard for every NIJA broker/account.

This guard is deliberately installed before bot startup. It closes three defects:
1. shared CapitalAuthority totals leaking into independent user cycles;
2. broker snapshots being treated as additive fills;
3. exits being raised to an entry minimum instead of closing the held position.
"""
from __future__ import annotations

import inspect
import logging
import os
import threading
from typing import Any

logger = logging.getLogger("nija.account_scope_exit_integrity_final")
_MARKER = "20260716-account-scope-exit-integrity-v3"
_LOCK = threading.RLock()
_PATCHED = False


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed == parsed and parsed >= 0.0 else default


def _broker_balance(broker: Any) -> float:
    if broker is None:
        return 0.0
    for name in (
        "_nija_last_account_balance_usd", "_nija_cycle_balance_usd",
        "last_account_balance", "_last_known_balance", "available_balance",
        "usd_balance", "cash_balance", "balance",
    ):
        value = _f(getattr(broker, name, 0.0))
        if value > 0:
            return value
    getter = getattr(broker, "get_account_balance", None)
    if callable(getter):
        try:
            raw = getter()
            if isinstance(raw, dict):
                for key in ("total_balance", "balance", "equity", "total_funds", "available_balance", "cash"):
                    value = _f(raw.get(key))
                    if value > 0:
                        return value
            value = _f(raw)
            if value > 0:
                return value
        except Exception as exc:
            logger.warning("ACCOUNT_SCOPE_BALANCE_REFRESH_FAILED marker=%s error=%s", _MARKER, exc)
    return 0.0


def _account_label(broker: Any) -> str:
    if broker is None:
        return "unknown"
    account = "platform"
    for name in ("account_id", "_account_id", "user_id", "account_name", "label"):
        value = getattr(broker, name, None)
        if value:
            account = str(value)
            break
    venue = type(broker).__name__.replace("Broker", "").lower() or "broker"
    return f"{account}:{venue}".lower().replace(" ", "_")


def _patch_trading_strategy() -> bool:
    try:
        from bot.trading_strategy import TradingStrategy
    except Exception:
        return False
    current = getattr(TradingStrategy, "run_cycle", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_account_scope_final", False):
        return True
    original = current

    def run_cycle(self: Any, broker: Any = None, user_mode: bool = False, *args: Any, **kwargs: Any):
        selected = broker if broker is not None else getattr(self, "broker", None)
        scoped = _broker_balance(selected)
        if selected is not None and scoped <= 0:
            logger.critical(
                "ACCOUNT_SCOPE_CAPITAL_UNAVAILABLE marker=%s account=%s action=fail_closed",
                _MARKER, _account_label(selected),
            )
            return int(_f(os.getenv("NIJA_ACCOUNT_SCOPE_RETRY_S", "10"), 10.0))

        # CapitalAuthority exposes computed read-only properties. Never overwrite
        # those properties for an account-local cycle; doing so raises
        # AttributeError and aborts position management and exits. Account scope
        # is carried only on the strategy/core/broker objects and the existing
        # per-cycle environment bridge.
        old_force = os.environ.get("NIJA_FORCE_TRADE_BALANCE")
        old_strategy_balance = getattr(self, "_nija_account_scoped_balance", None)
        old_strategy_active = getattr(self, "_nija_account_scope_active", None)
        core = getattr(self, "nija_core_loop", None)
        old_core_balance = getattr(core, "_nija_account_scoped_balance", None) if core is not None else None
        old_core_active = getattr(core, "_nija_account_scope_active", None) if core is not None else None
        old_core_public_balance = getattr(core, "balance", None) if core is not None else None
        old_broker_cycle_balance = getattr(selected, "_nija_cycle_balance_usd", None) if selected is not None else None

        if scoped > 0:
            os.environ["NIJA_FORCE_TRADE_BALANCE"] = f"{scoped:.12f}"
            setattr(self, "_nija_account_scoped_balance", scoped)
            setattr(self, "_nija_account_scope_active", True)
            if selected is not None:
                setattr(selected, "_nija_cycle_balance_usd", scoped)
            if core is not None:
                setattr(core, "_nija_account_scoped_balance", scoped)
                setattr(core, "_nija_account_scope_active", True)
                setattr(core, "balance", scoped)

        logger.critical(
            "ACCOUNT_SCOPE_CAPITAL_LOCKED marker=%s account=%s balance=$%.2f shared_ca_overridden=false",
            _MARKER, _account_label(selected), scoped,
        )
        try:
            return original(self, *args, broker=selected, user_mode=user_mode, **kwargs)
        finally:
            if old_force is None:
                os.environ.pop("NIJA_FORCE_TRADE_BALANCE", None)
            else:
                os.environ["NIJA_FORCE_TRADE_BALANCE"] = old_force

            if old_strategy_balance is None:
                try:
                    delattr(self, "_nija_account_scoped_balance")
                except AttributeError:
                    pass
            else:
                setattr(self, "_nija_account_scoped_balance", old_strategy_balance)
            if old_strategy_active is None:
                try:
                    delattr(self, "_nija_account_scope_active")
                except AttributeError:
                    pass
            else:
                setattr(self, "_nija_account_scope_active", old_strategy_active)

            if selected is not None:
                if old_broker_cycle_balance is None:
                    try:
                        delattr(selected, "_nija_cycle_balance_usd")
                    except AttributeError:
                        pass
                else:
                    setattr(selected, "_nija_cycle_balance_usd", old_broker_cycle_balance)

            if core is not None:
                if old_core_balance is None:
                    try:
                        delattr(core, "_nija_account_scoped_balance")
                    except AttributeError:
                        pass
                else:
                    setattr(core, "_nija_account_scoped_balance", old_core_balance)
                if old_core_active is None:
                    try:
                        delattr(core, "_nija_account_scope_active")
                    except AttributeError:
                        pass
                else:
                    setattr(core, "_nija_account_scope_active", old_core_active)
                if old_core_public_balance is not None:
                    setattr(core, "balance", old_core_public_balance)

    run_cycle._nija_account_scope_final = True  # type: ignore[attr-defined]
    run_cycle._nija_original = original  # type: ignore[attr-defined]
    TradingStrategy.run_cycle = run_cycle
    logger.critical("ACCOUNT_SCOPE_CAPITAL_GUARD_PATCHED marker=%s", _MARKER)
    return True


def _position_value(broker: Any, symbol: str) -> tuple[float, float]:
    getter = getattr(broker, "get_positions", None)
    if not callable(getter):
        return 0.0, 0.0
    try:
        raw = getter() or []
        positions = list(raw.values()) if isinstance(raw, dict) else list(raw)
    except Exception:
        return 0.0, 0.0
    want = str(symbol or "").upper().replace("-", "").replace("/", "")
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        got = str(pos.get("symbol") or pos.get("pair") or pos.get("asset") or "").upper().replace("-", "").replace("/", "")
        if got != want:
            continue
        qty = _f(pos.get("quantity") or pos.get("qty") or pos.get("volume") or pos.get("size"))
        value = _f(pos.get("market_value") or pos.get("value_usd") or pos.get("notional") or pos.get("position_value"))
        if value <= 0:
            price = _f(pos.get("current_price") or pos.get("market_price") or pos.get("price"))
            value = qty * price
        return qty, value
    return 0.0, 0.0


def _patch_execution_pipeline() -> bool:
    try:
        from bot.execution_pipeline import ExecutionPipeline
    except Exception:
        return False
    current = getattr(ExecutionPipeline, "execute", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_exit_exact_value_final", False):
        return True
    original = current
    signature = inspect.signature(original)

    def execute(self: Any, *args: Any, **kwargs: Any):
        try:
            bound = signature.bind_partial(self, *args, **kwargs)
            data = bound.arguments
        except Exception:
            data = kwargs
        side = str(data.get("side", kwargs.get("side", "")) or "").lower()
        intent = str(data.get("intent", kwargs.get("intent", "")) or "").lower()
        effect = str(data.get("position_effect", kwargs.get("position_effect", "")) or "").lower()
        strategy = str(data.get("strategy", kwargs.get("strategy", "")) or "").lower()
        is_exit = side in {"sell", "close"} and (
            intent in {"exit", "close", "reduce"} or effect in {"close", "reduce"} or "exit" in strategy
        )
        if is_exit:
            broker = data.get("broker") or kwargs.get("broker") or getattr(self, "broker", None)
            symbol = str(data.get("symbol", kwargs.get("symbol", "")) or "")
            qty, held_value = _position_value(broker, symbol)
            requested = _f(data.get("size_usd", kwargs.get("size_usd", 0.0)))
            if held_value > 0 and (requested <= 0 or requested > held_value * 1.01):
                replacement = max(0.01, held_value)
                if "size_usd" in kwargs:
                    kwargs["size_usd"] = replacement
                elif "size_usd" in data:
                    data["size_usd"] = replacement
                    try:
                        args = tuple(bound.args[1:])
                        kwargs = dict(bound.kwargs)
                    except Exception:
                        pass
                logger.critical(
                    "EXIT_SIZE_CLAMPED_TO_HELD_POSITION marker=%s symbol=%s qty=%.12f requested=$%.2f held_value=$%.2f final=$%.2f",
                    _MARKER, symbol, qty, requested, held_value, replacement,
                )
            kwargs.setdefault("force_trade", False)
            kwargs.setdefault("position_effect", "close")
        return original(self, *args, **kwargs)

    execute._nija_exit_exact_value_final = True  # type: ignore[attr-defined]
    execute._nija_original = original  # type: ignore[attr-defined]
    ExecutionPipeline.execute = execute
    logger.critical("EXIT_EXACT_POSITION_VALUE_GUARD_PATCHED marker=%s", _MARKER)
    return True


def _install_existing_adoption_guard() -> bool:
    try:
        from bot.position_adoption_exit_integrity_patch import install
        install()
        return True
    except Exception as exc:
        logger.warning("POSITION_ADOPTION_GUARD_CHAIN_FAILED marker=%s error=%s", _MARKER, exc)
        return False


def install() -> bool:
    global _PATCHED
    with _LOCK:
        adoption = _install_existing_adoption_guard()
        strategy = _patch_trading_strategy()
        pipeline = _patch_execution_pipeline()
        _PATCHED = adoption and strategy and pipeline
        os.environ["NIJA_ACCOUNT_SCOPE_EXIT_INTEGRITY_INSTALLED"] = "1" if _PATCHED else "0"
        if not _PATCHED:
            raise RuntimeError(
                f"account_scope_exit_integrity_incomplete:adoption={adoption}:strategy={strategy}:pipeline={pipeline}"
            )
        logger.critical(
            "ACCOUNT_SCOPE_EXIT_INTEGRITY_READY marker=%s adoption=%s strategy=%s pipeline=%s",
            _MARKER, adoption, strategy, pipeline,
        )
        return True


def installed_marker() -> str | None:
    return _MARKER if _PATCHED else None
