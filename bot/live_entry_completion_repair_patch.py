"""Runtime repairs for live-entry completion and startup activation noise.

This patch is intentionally narrow and import-hook based because the production
failure is startup/runtime ordering-sensitive:

* nonce lease stability should defer activation while the same lease matures,
  not emit false HARD FAIL noise during the last few seconds of the stability
  window;
* a scored/passed signal must always produce deterministic signal->execution
  telemetry, including the exact reason when it does not reach execute_action();
* the execution refetch candle gate must use the same minimum candle window as
  the scoring gate unless explicitly overridden;
* invalid volume sentinel values such as -99%/-100% must not be treated as real
  market-volume telemetry;
* successful OKX diagnostics should not pollute WARNING/ERROR logs.
"""

from __future__ import annotations

import builtins
import importlib
import inspect
import logging
import os
import sys
import textwrap
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.live_entry_completion_repair")
_TRUTHY = {"1", "true", "yes", "y", "on", "enabled"}


def _env_truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in _TRUTHY


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _nija_execution_min_candles() -> int:
    """Minimum candles required when a selected signal is re-fetched for execution."""

    # Scoring already accepts 50 candles in nija_core_loop. The previous hardcoded
    # execution refetch requirement of 100 could silently drop a SIGNAL_PASSED
    # candidate before execute_action(). Keep 50 as the default and allow operators
    # to raise it explicitly if they want stricter analysis.
    return max(10, _safe_int(os.getenv("NIJA_EXECUTION_MIN_CANDLES", "50"), 50))


class _SmartOKXLogger:
    """Logger adapter that demotes successful OKX diagnostic chatter only."""

    _DIAG_PREFIXES = (
        "OKX_AUTH_DETAIL",
        "OKX_HEADERS_DIAG",
        "OKX_REQUEST_DIAG",
        "OKX_RESPONSE_DIAG",
    )

    def __init__(self, base: logging.Logger) -> None:
        self._base = base

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)

    def warning(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        text = str(msg or "")
        if text.startswith(self._DIAG_PREFIXES):
            # Keep 200/account-balance diagnostics available for debugging but
            # stop labeling successful REST activity as a warning.
            self._base.debug(msg, *args, **kwargs)
            return
        self._base.warning(msg, *args, **kwargs)


def _patch_okx_runtime_patch(module: ModuleType) -> bool:
    if getattr(module, "_NIJA_OKX_DIAG_LOG_LEVEL_PATCHED", False):
        return True
    base_logger = getattr(module, "logger", logging.getLogger("nija.broker"))
    if not isinstance(base_logger, _SmartOKXLogger):
        setattr(module, "logger", _SmartOKXLogger(base_logger))
    setattr(module, "_NIJA_OKX_DIAG_LOG_LEVEL_PATCHED", True)
    logger.warning("OKX_DIAGNOSTIC_LOG_LEVEL_REPAIR_PATCHED module=%s", module.__name__)
    return True


def _patch_trading_state_machine(module: ModuleType) -> bool:
    """Replace nonce lease gate with wait/defer semantics for maturing same-owner leases."""

    if getattr(module, "_NIJA_NONCE_LEASE_WAIT_REPAIR_PATCHED", False):
        return True

    def _patched_nonce_writer_lease_gate() -> tuple[bool, str]:
        env_truthy = getattr(module, "_env_truthy", _env_truthy)
        if not env_truthy("NIJA_ENFORCE_NONCE_WRITER_LEASE", "true"):
            return True, ""

        platform_key = (
            os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
            or os.environ.get("KRAKEN_API_KEY", "").strip()
        )
        if not platform_key:
            return True, ""

        kraken_required = getattr(module, "_kraken_nonce_gates_required", lambda: True)
        try:
            if not kraken_required():
                logging.getLogger("nija.trading_state_machine").info(
                    "[NONCE LEASE GATE] skipped: Kraken credentials present but Kraken broker is not active"
                )
                return True, ""
        except Exception:
            # Preserve strict legacy behavior when topology inspection fails.
            pass

        retries = max(1, _safe_int(os.environ.get("NIJA_NONCE_LEASE_RETRIES", "5"), 5))
        retry_delay_s = max(0.10, _safe_float(os.environ.get("NIJA_NONCE_LEASE_RETRY_DELAY_S", "0.50"), 0.50))
        max_wait_s = max(0.0, _safe_float(os.environ.get("NIJA_NONCE_LEASE_STABILITY_MAX_WAIT_S", "12"), 12.0))
        started = time.monotonic()
        last_err = ""
        unstable_err = ""
        tsm_logger = logging.getLogger("nija.trading_state_machine")

        for attempt in range(1, retries + 1):
            try:
                try:
                    from bot.distributed_nonce_manager import get_distributed_nonce_manager, make_api_key_id
                    from bot.execution_authority_context import assert_startup_write_authority
                except ImportError:
                    from distributed_nonce_manager import get_distributed_nonce_manager, make_api_key_id  # type: ignore[import]
                    from execution_authority_context import assert_startup_write_authority  # type: ignore[import]

                key_id = make_api_key_id(platform_key)
                assert_startup_write_authority()
                manager = get_distributed_nonce_manager()
                manager.ensure_writer_lock(key_id)

                status_fn = getattr(manager, "get_writer_lease_status", None)
                status = status_fn(key_id) if callable(status_fn) else None
                if isinstance(status, dict):
                    token = status.get("token")
                    if token is not None and str(token).strip():
                        setattr(manager, "fencing_token", str(token).strip())
                else:
                    status = None

                stability_required_fn = getattr(module, "_nonce_lease_stability_requirement_s", lambda: 0.0)
                stability_required_s = float(stability_required_fn() or 0.0)
                if stability_required_s > 0:
                    if not isinstance(status, dict):
                        raise RuntimeError("nonce lease stability status unavailable")
                    if status.get("enabled") is False:
                        return True, ""
                    stable_for = status.get("stable_for_s")
                    if not isinstance(stable_for, (int, float)):
                        stable_for = 0.0
                    if float(stable_for) < stability_required_s:
                        token = status.get("token")
                        owner = status.get("owner_instance") or status.get("owner_id") or "<unknown>"
                        remaining_s = max(0.0, stability_required_s - float(stable_for))
                        unstable_err = (
                            "nonce lease unstable "
                            f"(stable_for={float(stable_for):.1f}s required={stability_required_s:.1f}s "
                            f"token={token} owner={owner})"
                        )
                        elapsed_s = max(0.0, time.monotonic() - started)
                        if elapsed_s + min(remaining_s, 5.0) <= max_wait_s or attempt < retries:
                            sleep_s = min(max(retry_delay_s, remaining_s + 0.10), 5.0)
                            tsm_logger.warning(
                                "[NONCE LEASE WAITING] activation deferred while Redis nonce lease matures "
                                "stable_for=%.1fs required=%.1fs remaining=%.1fs token=%s owner=%s "
                                "attempt=%d/%d sleep=%.2fs",
                                float(stable_for),
                                stability_required_s,
                                remaining_s,
                                token,
                                owner,
                                attempt,
                                retries,
                                sleep_s,
                            )
                            time.sleep(sleep_s)
                            continue
                        last_err = unstable_err
                        break
                return True, ""
            except Exception as exc:  # noqa: BLE001 - strict activation gate
                last_err = str(exc)
                if attempt < retries:
                    time.sleep(retry_delay_s)

        err = (
            "LIVE TRADING BLOCKED: nonce writer lease verification deferred/failed "
            f"after {retries} attempt(s). Redis nonce lease is required before "
            f"LIVE_ACTIVE is permitted. last_error={last_err or unstable_err}"
        )
        if "nonce lease unstable" in (last_err or unstable_err):
            tsm_logger.warning("[NONCE LEASE WAITING] %s", err)
        else:
            tsm_logger.critical("[NONCE LEASE HARD FAIL] %s", err)
        return False, err

    setattr(module, "_nonce_writer_lease_gate", _patched_nonce_writer_lease_gate)
    setattr(module, "_NIJA_NONCE_LEASE_WAIT_REPAIR_PATCHED", True)
    logging.getLogger("nija.trading_state_machine").warning(
        "NONCE_LEASE_WAIT_REPAIR_PATCHED module=%s", module.__name__
    )
    return True


def _wrap_execute_action(apex: Any) -> None:
    if apex is None or getattr(apex, "_NIJA_EXECUTION_TELEMETRY_WRAPPED", False):
        return
    original = getattr(apex, "execute_action", None)
    if not callable(original):
        return

    def _wrapped_execute_action(analysis: Any, symbol: str, *args: Any, **kwargs: Any) -> Any:
        action = None
        size = 0.0
        price = 0.0
        if isinstance(analysis, dict):
            action = analysis.get("action")
            size = _safe_float(analysis.get("position_size", 0.0))
            price = _safe_float(analysis.get("entry_price", 0.0))
        logger.critical(
            "SIGNAL_TO_EXECUTION_DISPATCH_ATTEMPT symbol=%s action=%s size=$%.2f price=%.8f",
            symbol,
            action or "unknown",
            size,
            price,
        )
        logger.critical(
            "ORDER_SIZING_STARTED symbol=%s action=%s requested_size=$%.2f entry_price=%.8f",
            symbol,
            action or "unknown",
            size,
            price,
        )
        logger.critical(
            "ORDER_COMPILER_STARTED symbol=%s action=%s size=$%.2f",
            symbol,
            action or "unknown",
            size,
        )
        logger.critical(
            "BROKER_ORDER_ATTEMPT symbol=%s action=%s size=$%.2f price=%.8f",
            symbol,
            action or "unknown",
            size,
            price,
        )
        try:
            result = original(analysis, symbol, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.critical(
                "BROKER_ORDER_ACK_OR_REJECT symbol=%s action=%s accepted=False exception=%r",
                symbol,
                action or "unknown",
                exc,
            )
            raise
        logger.critical(
            "ORDER_COMPILER_RESULT symbol=%s action=%s accepted=%s result=%r",
            symbol,
            action or "unknown",
            bool(result),
            result,
        )
        logger.critical(
            "BROKER_ORDER_ACK_OR_REJECT symbol=%s action=%s accepted=%s result=%r",
            symbol,
            action or "unknown",
            bool(result),
            result,
        )
        return result

    setattr(apex, "execute_action", _wrapped_execute_action)
    setattr(apex, "_NIJA_EXECUTION_TELEMETRY_WRAPPED", True)


def _patch_core_loop_source(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if cls is None or getattr(module, "_NIJA_LIVE_ENTRY_COMPLETION_PATCHED", False):
        return bool(getattr(module, "_NIJA_LIVE_ENTRY_COMPLETION_PATCHED", False))

    setattr(module, "_nija_execution_min_candles", _nija_execution_min_candles)
    original_method = getattr(cls, "_phase3_scan_and_enter", None)
    if callable(original_method):
        try:
            src = textwrap.dedent(inspect.getsource(original_method))
            replacements = 0

            old_exec_fetch = (
                "            if df is None or len(df) < 100:\n"
                "                _funnel[\"market_data\"] = (\"FAIL\", \"DATA_INSUFFICIENT\")\n"
                "                continue"
            )
            new_exec_fetch = (
                "            _execution_min_candles = _nija_execution_min_candles()\n"
                "            _df_exec_len = len(df) if df is not None else 0\n"
                "            if df is None or _df_exec_len < _execution_min_candles:\n"
                "                _funnel[\"market_data\"] = (\"FAIL\", \"DATA_INSUFFICIENT\")\n"
                "                blocked += 1\n"
                "                _gate_rejections[\"data_insufficient\"] = _gate_rejections.get(\"data_insufficient\", 0) + 1\n"
                "                logger.critical(\n"
                "                    \"SIGNAL_PASSED_BUT_NOT_EXECUTED reason=execution_data_insufficient \"\n"
                "                    \"symbol=%s df_len=%d required=%d cycle_id=%s\",\n"
                "                    sig.symbol,\n"
                "                    _df_exec_len,\n"
                "                    _execution_min_candles,\n"
                "                    getattr(snapshot, \"cycle_id\", \"n/a\"),\n"
                "                )\n"
                "                continue"
            )
            if old_exec_fetch in src:
                src = src.replace(old_exec_fetch, new_exec_fetch, 1)
                replacements += 1

            old_volume = (
                "                            _diag_vol_pct = (_cur_vol / _avg_vol - 1.0) * 100.0\n"
                "                            _volume_pct_sum += _diag_vol_pct\n"
                "                            _volume_pct_count += 1"
            )
            new_volume = (
                "                            _raw_diag_vol_pct = (_cur_vol / _avg_vol - 1.0) * 100.0\n"
                "                            if _raw_diag_vol_pct <= -90.0:\n"
                "                                logger.warning(\n"
                "                                    \"VOLUME_SENTINEL_NORMALIZED symbol=%s raw_vol_pct=%.1f using=0.0 \"\n"
                "                                    \"reason=invalid_or_missing_volume_baseline\",\n"
                "                                    symbol,\n"
                "                                    _raw_diag_vol_pct,\n"
                "                                )\n"
                "                                _diag_vol_pct = 0.0\n"
                "                            else:\n"
                "                                _diag_vol_pct = _raw_diag_vol_pct\n"
                "                                _volume_pct_sum += _diag_vol_pct\n"
                "                                _volume_pct_count += 1"
            )
            if old_volume in src:
                src = src.replace(old_volume, new_volume, 1)
                replacements += 1

            old_submit = "            success = self.apex.execute_action(analysis, sig.symbol)"
            new_submit = (
                "            logger.critical(\n"
                "                \"SIGNAL_TO_EXECUTION_DISPATCH_ATTEMPT symbol=%s side=%s action=%s \"\n"
                "                \"score=%.1f cycle_id=%s\",\n"
                "                sig.symbol, sig.side, action, sig.composite_score, getattr(snapshot, \"cycle_id\", \"n/a\"),\n"
                "            )\n"
                "            logger.critical(\n"
                "                \"ORDER_SIZING_STARTED symbol=%s action=%s position_size=$%.2f entry_price=%.8f\",\n"
                "                sig.symbol, action,\n"
                "                float(analysis.get(\"position_size\", 0.0) or 0.0),\n"
                "                float(analysis.get(\"entry_price\", 0.0) or 0.0),\n"
                "            )\n"
                "            logger.critical(\"ORDER_COMPILER_STARTED symbol=%s action=%s\", sig.symbol, action)\n"
                "            logger.critical(\n"
                "                \"BROKER_ORDER_ATTEMPT symbol=%s side=%s action=%s size=$%.2f price=%.8f\",\n"
                "                sig.symbol, sig.side, action,\n"
                "                float(analysis.get(\"position_size\", 0.0) or 0.0),\n"
                "                float(analysis.get(\"entry_price\", 0.0) or 0.0),\n"
                "            )\n"
                "            success = self.apex.execute_action(analysis, sig.symbol)\n"
                "            logger.critical(\n"
                "                \"ORDER_COMPILER_RESULT symbol=%s action=%s accepted=%s\",\n"
                "                sig.symbol, action, bool(success),\n"
                "            )\n"
                "            logger.critical(\n"
                "                \"BROKER_ORDER_ACK_OR_REJECT symbol=%s side=%s action=%s accepted=%s\",\n"
                "                sig.symbol, sig.side, action, bool(success),\n"
                "            )"
            )
            if old_submit in src:
                src = src.replace(old_submit, new_submit, 1)
                replacements += 1

            old_force_submit = "_ft_success = self.apex.execute_action(_ft_analysis, _best_volume_symbol)"
            new_force_submit = (
                "logger.critical(\n"
                "                            \"SIGNAL_TO_EXECUTION_DISPATCH_ATTEMPT symbol=%s action=%s \"\n"
                "                            \"reason=force_trade_direct cycle_id=%s\",\n"
                "                            _best_volume_symbol, _ft_action, snapshot.cycle_id or \"n/a\",\n"
                "                        )\n"
                "                        logger.critical(\n"
                "                            \"BROKER_ORDER_ATTEMPT symbol=%s action=%s size=$%.2f price=%.8f reason=force_trade_direct\",\n"
                "                            _best_volume_symbol, _ft_action, _ft_size, _ft_price,\n"
                "                        )\n"
                "                        _ft_success = self.apex.execute_action(_ft_analysis, _best_volume_symbol)\n"
                "                        logger.critical(\n"
                "                            \"BROKER_ORDER_ACK_OR_REJECT symbol=%s action=%s accepted=%s reason=force_trade_direct\",\n"
                "                            _best_volume_symbol, _ft_action, bool(_ft_success),\n"
                "                        )"
            )
            if old_force_submit in src:
                src = src.replace(old_force_submit, new_force_submit, 1)
                replacements += 1

            if replacements:
                exec(src, module.__dict__)
                patched = module.__dict__.get("_phase3_scan_and_enter")
                if callable(patched):
                    setattr(cls, "_phase3_scan_and_enter", patched)
                    logger.warning(
                        "LIVE_ENTRY_COMPLETION_SOURCE_PATCHED module=%s replacements=%d execution_min_candles=%d",
                        module.__name__,
                        replacements,
                        _nija_execution_min_candles(),
                    )
            else:
                logger.warning(
                    "LIVE_ENTRY_COMPLETION_SOURCE_PATCH_SKIPPED module=%s reason=no_source_patterns_matched",
                    module.__name__,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LIVE_ENTRY_COMPLETION_SOURCE_PATCH_FAILED module=%s err=%s", module.__name__, exc)

    original_init = getattr(cls, "__init__", None)
    if callable(original_init) and not getattr(cls, "_NIJA_INIT_EXEC_TELEMETRY_PATCHED", False):
        def _patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
            original_init(self, *args, **kwargs)
            _wrap_execute_action(getattr(self, "apex", None))

        setattr(cls, "__init__", _patched_init)
        setattr(cls, "_NIJA_INIT_EXEC_TELEMETRY_PATCHED", True)

    setattr(module, "_NIJA_LIVE_ENTRY_COMPLETION_PATCHED", True)
    logger.warning("LIVE_ENTRY_COMPLETION_REPAIR_PATCHED module=%s", module.__name__)
    return True


def _apply_to_loaded_modules() -> None:
    for name, module in list(sys.modules.items()):
        if module is None:
            continue
        if name in {"bot.trading_state_machine", "trading_state_machine"}:
            try:
                _patch_trading_state_machine(module)
            except Exception as exc:  # noqa: BLE001
                logger.warning("NONCE_LEASE_WAIT_REPAIR_FAILED module=%s err=%s", name, exc)
        elif name in {"bot.nija_core_loop", "nija_core_loop"}:
            try:
                _patch_core_loop_source(module)
            except Exception as exc:  # noqa: BLE001
                logger.warning("LIVE_ENTRY_COMPLETION_REPAIR_FAILED module=%s err=%s", name, exc)
        elif name in {"bot.okx_runtime_patch", "okx_runtime_patch"}:
            try:
                _patch_okx_runtime_patch(module)
            except Exception as exc:  # noqa: BLE001
                logger.warning("OKX_DIAGNOSTIC_LOG_LEVEL_REPAIR_FAILED module=%s err=%s", name, exc)


def install_import_hook() -> None:
    """Install import hook and patch already-loaded runtime modules."""

    if getattr(builtins, "_NIJA_LIVE_ENTRY_COMPLETION_IMPORT_HOOK_INSTALLED", False):
        _apply_to_loaded_modules()
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        module = original_import(name, globals, locals, fromlist, level)
        target_names = {
            name,
            f"{name}.{fromlist[0]}" if fromlist else name,
        }
        if (
            name in {"bot.trading_state_machine", "trading_state_machine"}
            or name in {"bot.nija_core_loop", "nija_core_loop"}
            or name in {"bot.okx_runtime_patch", "okx_runtime_patch"}
            or any(str(item).endswith(("trading_state_machine", "nija_core_loop", "okx_runtime_patch")) for item in target_names)
        ):
            _apply_to_loaded_modules()
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_LIVE_ENTRY_COMPLETION_IMPORT_HOOK_INSTALLED", True)
    _apply_to_loaded_modules()
    logger.warning("LIVE_ENTRY_COMPLETION_REPAIR_INSTALL_REQUESTED")
