"""Post-lock readiness, live-capital convergence, and startup log hardening.

This module is imported early by ``bot.__init__``. It never enables live trading
by itself. ``LIVE_CAPITAL_VERIFIED`` remains an explicit operator-controlled
master switch. The patch only:

* normalizes an explicitly configured boolean value (including quoted Railway
  values such as ``\"true\"``);
* observes real, positive, fresh broker-backed capital and then asks the normal
  runtime-authority convergence path to re-evaluate;
* installs the final execution contract before the long startup patch chain;
* marks readiness from successful runtime events; and
* suppresses duplicate patch-install chatter without hiding execution failures.
"""

from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from collections.abc import Mapping
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.post_lock_capital_refresh")
_INSTALLED = False
_PATCHED = "__nija_post_lock_capital_refresh_patch__"
_MONITOR_STARTED = False
_MONITOR_LOCK = threading.Lock()
_CONVERGENCE_LOCK = threading.Lock()
_LAST_CONVERGENCE_SIGNATURE = ""
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_FALSE = {"0", "false", "no", "off", "disabled", "n"}


class _PatchNoiseFilter(logging.Filter):
    """Throttle repeated installation markers while preserving the first event."""

    _MARKERS = (
        "SPENDABLE_QUOTE_ROUTING_PATCHED",
        "LIVE_ENTRY_FIXES_RUN_SCAN_WIRED",
        "LIVE_ENTRY_FIXES_PHASE3_WIRED",
        "TRADING_STATE_DISPATCH_LATCH_REPAIR_PATCHED",
        "LIVE_ACTIVE_EXECUTION_GATE_FINAL_PATCHED",
        "EXCHANGE_ORDER_COMPILER_KRAKEN_ENTRY_TARGET_PATCHED",
        "POSITION_SIZER_KRAKEN_ENTRY_TARGET_PATCHED",
        "ECEL_KRAKEN_ENTRY_TARGET_PATCHED",
    )
    _lock = threading.Lock()
    _last_seen: dict[str, float] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        marker = next((token for token in self._MARKERS if token in message), "")
        if not marker:
            return True
        now = time.monotonic()
        interval = max(5.0, _float_env("NIJA_PATCH_INSTALL_LOG_THROTTLE_S", 60.0))
        with self._lock:
            previous = self._last_seen.get(marker, 0.0)
            if now - previous < interval:
                return False
            self._last_seen[marker] = now
        return True


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except Exception:
        return default


def _clean_env_value(value: Any) -> str:
    text = str(value or "").strip().lstrip("\ufeff")
    while len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text.strip().lower()


def _truthy_env(name: str) -> bool:
    return _clean_env_value(os.environ.get(name, "")) in _TRUE


def _normalize_explicit_boolean(name: str) -> tuple[bool, str, str]:
    """Normalize a present boolean variable without creating or enabling it."""

    if name not in os.environ:
        return False, "missing", ""
    raw = str(os.environ.get(name, ""))
    cleaned = _clean_env_value(raw)
    if cleaned in _TRUE:
        canonical = "true"
    elif cleaned in _FALSE:
        canonical = "false"
    else:
        return False, "invalid", cleaned
    changed = raw != canonical
    os.environ[name] = canonical
    return changed, canonical, cleaned


def _normalize_explicit_controls() -> None:
    statuses: list[str] = []
    for name in (
        "LIVE_CAPITAL_VERIFIED",
        "DRY_RUN_MODE",
        "PAPER_MODE",
        "NIJA_RUNTIME_EXECUTION_AUTHORITY",
    ):
        changed, state, _cleaned = _normalize_explicit_boolean(name)
        statuses.append(f"{name}={state}{':normalized' if changed else ''}")
    logger.warning("LIVE_CONTROL_ENV_STATUS %s", " ".join(statuses))
    if not _truthy_env("LIVE_CAPITAL_VERIFIED"):
        logger.warning(
            "LIVE_CAPITAL_OPERATOR_SWITCH_OFF trading_disabled=true "
            "action=set LIVE_CAPITAL_VERIFIED=true in Railway only after intentional approval"
        )


def _install_noise_filter() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_nija_patch_noise_filter_20260710b", False):
            continue
        handler.addFilter(_PatchNoiseFilter())
        setattr(handler, "_nija_patch_noise_filter_20260710b", True)
    logger.warning(
        "PATCH_INSTALL_LOG_THROTTLE_ENABLED interval_s=%.1f",
        _float_env("NIJA_PATCH_INSTALL_LOG_THROTTLE_S", 60.0),
    )


def _install_final_execution_contract() -> None:
    """Install the immutable execution contract before later patch modules load."""

    try:
        module = importlib.import_module("bot.execution_pipeline_runtime_patch")
        installer = getattr(module, "install_import_hook", None)
        if callable(installer):
            installer()
        logger.warning("FINAL_EXECUTION_CONTRACT_EARLY_INSTALL_CONFIRMED marker=20260710a")
    except Exception as exc:
        logger.warning("FINAL_EXECUTION_CONTRACT_EARLY_INSTALL_FAILED err=%s", exc)


def _mark(component: str, reason: str) -> None:
    try:
        try:
            from bot.readiness_table import mark_ready, snapshot
        except ImportError:
            from readiness_table import mark_ready, snapshot  # type: ignore[import]
        if snapshot().get(component) is True:
            return
        mark_ready(component)
        logger.critical("POST_LOCK_READY component=%s reason=%s", component, reason)
    except Exception as exc:
        logger.debug("POST_LOCK_READY mark failed component=%s error=%s", component, exc)


def _mark_many(components: tuple[str, ...], reason: str) -> None:
    for component in components:
        _mark(component, reason)
    _maybe_mark_bootstrap(reason)


def _maybe_mark_bootstrap(reason: str) -> None:
    try:
        try:
            from bot.readiness_table import snapshot
        except ImportError:
            from readiness_table import snapshot  # type: ignore[import]
        table = snapshot()
    except Exception:
        return
    required = (
        "broker_connected",
        "balance_hydrated",
        "authority_ready",
        "capital_ready",
        "risk_ready",
        "strategy_ready",
        "execution_ready",
        "nonce_ready",
    )
    if all(table.get(key) is True for key in required):
        _mark("bootstrap_ready", reason)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value or 0.0)
        return result if result == result else default
    except Exception:
        return default


def _capital_result(result: Any) -> dict[str, Any]:
    if isinstance(result, Mapping):
        return dict(result)
    out: dict[str, Any] = {}
    for name in (
        "ready",
        "total_capital",
        "real_capital",
        "valid_brokers",
        "broker_count",
        "kraken_capital",
        "snapshot_source",
        "bootstrap_seed",
    ):
        try:
            value = getattr(result, name)
        except Exception:
            continue
        out[name] = value
    return out


def _capital_authority_proof() -> tuple[bool, str]:
    try:
        from bot.capital_authority import get_capital_authority, get_capital_system_gate

        authority = get_capital_authority()
        hydrated = bool(getattr(authority, "is_hydrated", False))
        real = _number(getattr(authority, "real_capital", 0.0))
        getter = getattr(authority, "get_real_capital", None)
        if callable(getter):
            real = max(real, _number(getter()))
        fresh = True
        fresh_getter = getattr(authority, "is_fresh", None)
        if callable(fresh_getter):
            try:
                fresh = bool(fresh_getter(ttl_s=180.0))
            except TypeError:
                fresh = bool(fresh_getter())
        gate = get_capital_system_gate()
        gate_ready = bool(gate.is_set())
        ok = hydrated and real > 0.0 and fresh and gate_ready
        return ok, f"hydrated={hydrated} real={real:.2f} fresh={fresh} capital_gate={gate_ready}"
    except Exception as exc:
        return False, f"capital_authority_probe_failed:{exc}"


def _request_safe_convergence(source: str, result: Any = None) -> bool:
    """Re-evaluate normal authority gates after verified capital becomes ready."""

    global _LAST_CONVERGENCE_SIGNATURE
    if not _truthy_env("LIVE_CAPITAL_VERIFIED"):
        return False
    if _truthy_env("DRY_RUN_MODE") or _truthy_env("PAPER_MODE"):
        return False

    payload = _capital_result(result)
    if payload:
        ready = bool(_number(payload.get("ready")))
        total = max(_number(payload.get("total_capital")), _number(payload.get("real_capital")))
        valid = max(
            int(_number(payload.get("valid_brokers"))),
            int(_number(payload.get("broker_count"))),
        )
        source_name = str(payload.get("snapshot_source") or "").strip().lower()
        bootstrap_seed = bool(_number(payload.get("bootstrap_seed")))
        live_source = source_name == "live_exchange" or bootstrap_seed
        if not (ready and total > 0.0 and valid > 0 and live_source):
            return False
    else:
        total = 0.0
        valid = 0
        source_name = "capital_system_gate"

    proof_ok, proof = _capital_authority_proof()
    if not proof_ok:
        logger.info("POST_LOCK_CAPITAL_CONVERGENCE_WAITING source=%s proof=%s", source, proof)
        return False

    signature = f"{source}:{source_name}:{total:.2f}:{valid}:{proof}"
    with _CONVERGENCE_LOCK:
        if signature == _LAST_CONVERGENCE_SIGNATURE:
            return False
        _LAST_CONVERGENCE_SIGNATURE = signature

    _mark_many(("broker_connected", "balance_hydrated", "capital_ready"), signature)
    converged = False
    try:
        module = importlib.import_module("bot.runtime_authority_convergence_repair_patch")
        converge = getattr(module, "converge_runtime_authority", None)
        if callable(converge):
            converged = bool(converge(f"post_lock_capital:{source}"))
    except Exception as exc:
        logger.warning("POST_LOCK_CAPITAL_CONVERGENCE_CALL_FAILED source=%s err=%s", source, exc)
    logger.critical(
        "POST_LOCK_LIVE_CAPITAL_VERIFIED source=%s snapshot_source=%s total=%.2f "
        "valid_brokers=%d proof=%s convergence_triggered=%s",
        source,
        source_name,
        total,
        valid,
        proof,
        converged,
    )
    return True


def _start_capital_gate_monitor() -> None:
    global _MONITOR_STARTED
    with _MONITOR_LOCK:
        if _MONITOR_STARTED:
            return
        _MONITOR_STARTED = True

    def _monitor() -> None:
        if not _truthy_env("LIVE_CAPITAL_VERIFIED"):
            return
        timeout_s = max(30.0, _float_env("NIJA_POST_LOCK_CAPITAL_MONITOR_SECONDS", 300.0))
        try:
            from bot.capital_authority import get_capital_system_gate

            if not get_capital_system_gate().wait(timeout=timeout_s):
                logger.warning("POST_LOCK_CAPITAL_GATE_MONITOR_TIMEOUT timeout_s=%.1f", timeout_s)
                return
            _request_safe_convergence("capital_system_gate")
        except Exception as exc:
            logger.warning("POST_LOCK_CAPITAL_GATE_MONITOR_FAILED err=%s", exc)

    threading.Thread(target=_monitor, name="post-lock-capital-gate-monitor", daemon=True).start()


def _patch_nonce_module(module: Any) -> None:
    cls = getattr(module, "DistributedNonceManager", None)
    if not isinstance(cls, type):
        return
    original = getattr(cls, "ensure_writer_lock", None)
    if not callable(original) or getattr(original, _PATCHED, False):
        return

    @wraps(original)
    def wrapper(self: Any, api_key_id: str, *args: Any, **kwargs: Any):
        result = original(self, api_key_id, *args, **kwargs)
        _mark_many(("authority_ready", "nonce_ready"), f"writer_lock:{api_key_id}")
        _request_safe_convergence("writer_lock")
        return result

    setattr(wrapper, _PATCHED, True)
    setattr(cls, "ensure_writer_lock", wrapper)
    logger.warning("POST_LOCK_CAPITAL_REFRESH_PATCHED DistributedNonceManager.ensure_writer_lock")


def _patch_mabm_module(module: Any) -> None:
    cls = getattr(module, "MultiAccountBrokerManager", None)
    if not isinstance(cls, type):
        return
    original = getattr(cls, "refresh_capital_authority", None)
    if not callable(original) or getattr(original, _PATCHED, False):
        return

    @wraps(original)
    def wrapper(self: Any, *args: Any, **kwargs: Any):
        result = original(self, *args, **kwargs)
        payload = _capital_result(result)
        ready = bool(_number(payload.get("ready")))
        total = max(_number(payload.get("total_capital")), _number(payload.get("real_capital")))
        valid = max(
            int(_number(payload.get("valid_brokers"))),
            int(_number(payload.get("broker_count"))),
        )
        if ready and total > 0.0 and valid > 0:
            _mark_many(
                ("broker_connected", "balance_hydrated", "capital_ready"),
                f"capital_refresh:total={total:.2f}:brokers={valid}",
            )
            _request_safe_convergence("refresh_capital_authority", result)
        return result

    setattr(wrapper, _PATCHED, True)
    setattr(cls, "refresh_capital_authority", wrapper)
    logger.warning("POST_LOCK_CAPITAL_REFRESH_PATCHED MultiAccountBrokerManager.refresh_capital_authority")


def _patch_strategy_module(module: Any) -> None:
    cls = getattr(module, "TradingStrategy", None)
    if isinstance(cls, type):
        original = getattr(cls, "__init__", None)
        if callable(original) and not getattr(original, _PATCHED, False):

            @wraps(original)
            def wrapper(self: Any, *args: Any, **kwargs: Any):
                result = original(self, *args, **kwargs)
                _mark_many(("risk_ready", "strategy_ready"), "TradingStrategy.__init__")
                return result

            setattr(wrapper, _PATCHED, True)
            setattr(cls, "__init__", wrapper)
            logger.warning("POST_LOCK_CAPITAL_REFRESH_PATCHED TradingStrategy.__init__")
        _mark_many(("risk_ready", "strategy_ready"), "TradingStrategy.imported")


def _patch_module(module: Any) -> None:
    name = str(getattr(module, "__name__", ""))
    if name.endswith("distributed_nonce_manager"):
        _patch_nonce_module(module)
    elif name.endswith("multi_account_broker_manager"):
        _patch_mabm_module(module)
    elif name.endswith("trading_strategy"):
        _patch_strategy_module(module)
    elif any(token in name for token in ("execution", "pipeline_order_submitter", "nija_core_loop")):
        _mark_many(("execution_ready",), f"module_import:{name}")


def install_import_hook() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    _normalize_explicit_controls()
    _install_noise_filter()
    _install_final_execution_contract()
    for module in list(sys.modules.values()):
        try:
            _patch_module(module)
        except Exception:
            pass

    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            _patch_module(module)
        except Exception:
            pass
        return module

    builtins.__import__ = guarded_import
    _start_capital_gate_monitor()
    logger.warning("POST_LOCK_CAPITAL_REFRESH_INSTALL_COMPLETE marker=20260710b")
