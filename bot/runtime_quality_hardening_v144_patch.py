"""NIJA runtime quality hardening v144.

Closes the remaining production gaps observed in the 2026-08-18 runtime log:

* startup reconciliation is fail-closed for live entries;
* an already-LIVE process cannot dispatch new exposure until reconciliation is
  both complete and CLEAN/CLEAN_START (reduce/exit traffic is never blocked);
* live AI candidates must pass the canonical AI entry gate, rather than merely
  clearing a relaxed composite-score floor;
* successful readiness/convergence/import events are de-noised so CRITICAL is
  reserved for genuine safety failures;
* capital refreshes publish an explicit completion result; and
* entry dispatch publishes a structured final result so SIGNAL_PASSED cannot be
  mistaken for an executed order.

The patch is intentionally narrow and idempotent. It does not relax kill-switch,
nonce, writer, capital, position-sync, risk, sizing, or broker protections.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_quality_hardening_v144")
MARKER = "20260818-runtime-quality-hardening-v144"
RELEASE_ID = "20260818-runtime-convergence-v144"
_FLAG = "NIJA_RUNTIME_QUALITY_HARDENING_V144_INSTALLED"
_READY_FLAG = "NIJA_RUNTIME_QUALITY_HARDENING_V144_READY"
_PATCH_ATTR = "_nija_runtime_quality_hardening_v144"
_LOCK = threading.RLock()
_INSTALLED = False
_MONITOR_STARTED = False
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _live_runtime() -> bool:
    return not _truthy("DRY_RUN_MODE") and not _truthy("PAPER_MODE")


def _reconciliation_status() -> tuple[bool, str]:
    """Return strict restart-reconciliation status for live entry authority."""
    status = str(os.environ.get("NIJA_RECONCILIATION_STATUS", "") or "").strip().upper()
    complete = _truthy("NIJA_RECONCILIATION_COMPLETE", "false")
    if complete and status in {"CLEAN", "CLEAN_START"}:
        return True, ""
    return False, f"status={status or 'missing'} complete={str(complete).lower()}"


def _entry_increases_exposure(request: Any) -> bool:
    """Conservatively classify entry requests while always allowing reductions."""
    if bool(getattr(request, "reduce_only", False)):
        return False
    intent = str(getattr(request, "intent_type", "entry") or "entry").strip().lower()
    effect = str(getattr(request, "position_effect", "") or "").strip().lower()
    side = str(getattr(request, "side", "") or "").strip().lower()
    if intent in {"reduce", "exit", "close", "liquidate", "liquidation"}:
        return False
    if effect in {"reduce", "exit", "close", "liquidate", "liquidation"}:
        return False
    # Unknown side on an entry-intent request is treated as exposure-increasing.
    return side not in {"sell", "short", "reduce", "exit", "close"}


def _pipeline_failure(module: ModuleType, request: Any, started: float, reason: str) -> Any:
    result_cls = getattr(module, "PipelineResult", None)
    if callable(result_cls):
        return result_cls(
            success=False,
            symbol=str(getattr(request, "symbol", "") or ""),
            side=str(getattr(request, "side", "") or ""),
            size_usd=float(getattr(request, "size_usd", 0.0) or 0.0),
            error=reason,
            latency_ms=(time.monotonic() - started) * 1000.0,
        )
    raise RuntimeError(reason)


def _result_success(result: Any) -> bool:
    if isinstance(result, dict):
        if "success" in result:
            return bool(result.get("success"))
        status = str(result.get("status", "") or "").lower()
        return status in {"ok", "success", "submitted", "accepted", "filled"}
    return bool(getattr(result, "success", False))


def _result_order_id(result: Any) -> str:
    fields = ("order_id", "id", "broker_order_id", "client_order_id")
    if isinstance(result, dict):
        for field in fields:
            value = result.get(field)
            if value:
                return str(value)
        nested = result.get("broker_response")
        if isinstance(nested, dict):
            for field in fields:
                value = nested.get(field)
                if value:
                    return str(value)
        return ""
    for field in fields:
        value = getattr(result, field, None)
        if value:
            return str(value)
    return ""


def _result_error(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("error") or result.get("message") or "")[:240]
    return str(getattr(result, "error", "") or getattr(result, "message", "") or "")[:240]


def _patch_trading_state_machine(module: ModuleType) -> bool:
    current = getattr(module, "_startup_reconciliation_gate", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def strict_reconciliation_gate() -> tuple[bool, str]:
        # Simulation can explicitly opt out. Live trading never can.
        if not _live_runtime() and not _truthy("NIJA_REQUIRE_STARTUP_RECONCILIATION", "true"):
            return True, ""
        ok, detail = _reconciliation_status()
        if not ok:
            LOGGER.warning(
                "RECONCILIATION_GATE_V144_BLOCK marker=%s %s live=%s new_entries_fail_closed=true exits_unaffected=true",
                MARKER,
                detail,
                str(_live_runtime()).lower(),
            )
        return ok, detail

    setattr(strict_reconciliation_gate, _PATCH_ATTR, True)
    setattr(strict_reconciliation_gate, "__wrapped__", current)
    module._startup_reconciliation_gate = strict_reconciliation_gate
    return True


def _patch_execution_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    current = getattr(cls, "execute", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def execute_v144(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        entry = _entry_increases_exposure(request)
        symbol = str(getattr(request, "symbol", "") or "")
        side = str(getattr(request, "side", "") or "")
        if _live_runtime() and entry:
            recon_ok, recon_detail = _reconciliation_status()
            if not recon_ok:
                reason = f"STARTUP_RECONCILIATION_INCOMPLETE {recon_detail}"
                LOGGER.error(
                    "ENTRY_DISPATCH_BLOCKED marker=%s symbol=%s side=%s reason=%s exits_unaffected=true",
                    MARKER,
                    symbol,
                    side,
                    reason,
                )
                return _pipeline_failure(module, request, started, reason)

        result = current(self, request, *args, **kwargs)
        if entry:
            success = _result_success(result)
            order_id = _result_order_id(result)
            error = _result_error(result)
            LOGGER.info(
                "ENTRY_DISPATCH_RESULT marker=%s symbol=%s side=%s success=%s order_id=%s error=%s latency_ms=%.1f",
                MARKER,
                symbol,
                side,
                str(success).lower(),
                order_id or "none",
                error or "none",
                (time.monotonic() - started) * 1000.0,
            )
        return result

    setattr(execute_v144, _PATCH_ATTR, True)
    setattr(execute_v144, "__wrapped__", current)
    cls.execute = execute_v144
    return True


def _patch_ai_engine(module: ModuleType) -> bool:
    cls = getattr(module, "NijaAIEngine", None)
    current = getattr(cls, "evaluate_symbol", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def evaluate_symbol_v144(self: Any, *args: Any, **kwargs: Any) -> Any:
        signal = current(self, *args, **kwargs)
        if signal is None or not _live_runtime():
            return signal

        metadata = dict(getattr(signal, "metadata", {}) or {})
        gate_passed = metadata.get("gate_passed") is True
        gate_quality = float(metadata.get("gate_quality", 0.0) or 0.0)
        require_gate = _truthy("NIJA_LIVE_AI_GATE_REQUIRED", "true")
        try:
            min_gate_quality = max(
                0.0,
                float(os.environ.get("NIJA_LIVE_MIN_GATE_QUALITY_PCT", "0") or 0.0),
            )
        except Exception:
            min_gate_quality = 0.0

        if require_gate and not gate_passed:
            LOGGER.warning(
                "LIVE_AI_SIGNAL_REJECTED marker=%s symbol=%s side=%s reason=canonical_gate_not_passed composite=%.2f gate_quality=%.2f",
                MARKER,
                getattr(signal, "symbol", kwargs.get("symbol", "")),
                getattr(signal, "side", kwargs.get("side", "")),
                float(getattr(signal, "composite_score", 0.0) or 0.0),
                gate_quality,
            )
            return None
        if gate_quality + 1e-9 < min_gate_quality:
            LOGGER.warning(
                "LIVE_AI_SIGNAL_REJECTED marker=%s symbol=%s side=%s reason=gate_quality_below_floor gate_quality=%.2f required=%.2f",
                MARKER,
                getattr(signal, "symbol", kwargs.get("symbol", "")),
                getattr(signal, "side", kwargs.get("side", "")),
                gate_quality,
                min_gate_quality,
            )
            return None
        return signal

    setattr(evaluate_symbol_v144, _PATCH_ATTR, True)
    setattr(evaluate_symbol_v144, "__wrapped__", current)
    cls.evaluate_symbol = evaluate_symbol_v144
    os.environ.setdefault("NIJA_LIVE_AI_GATE_REQUIRED", "true")
    return True


def _patch_readiness_table(module: ModuleType) -> bool:
    current = getattr(module, "mark_ready", None)
    setter = getattr(module, "set_ready", None)
    table = getattr(module, "_TABLE", None)
    lock = getattr(module, "_LOCK", None)
    logger = getattr(module, "logger", logging.getLogger("nija.readiness_table"))
    if not callable(current) or not callable(setter) or not isinstance(table, dict):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    def mark_ready_v144(component: str) -> None:
        try:
            if lock is not None:
                with lock:
                    was_ready = bool(table.get(component, False))
            else:
                was_ready = bool(table.get(component, False))
        except Exception:
            was_ready = False
        setter(component, True)
        if was_ready:
            logger.debug("READINESS_TABLE unchanged component=%s ready=true", component)
        else:
            logger.info("READINESS_TABLE_READY component=%s table=%s", component, dict(table))

    setattr(mark_ready_v144, _PATCH_ATTR, True)
    setattr(mark_ready_v144, "__wrapped__", current)
    module.mark_ready = mark_ready_v144
    return True


def _patch_canonical_import_handoff(module: ModuleType) -> bool:
    current = getattr(module, "_resolve_target", None)
    canonical_import = getattr(module, "_canonical_import", None)
    reapply = getattr(module, "_reapply_core_safety", None)
    logger = getattr(module, "LOGGER", logging.getLogger("nija.canonical_core_import_handoff_v125"))
    marker = str(getattr(module, "MARKER", "") or "")
    if not callable(current) or not callable(canonical_import):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    def resolve_target_v144(name: str) -> ModuleType:
        started = time.monotonic()
        target = canonical_import(name)
        if name == "bot.nija_core_loop" and callable(reapply) and not reapply(target):
            raise RuntimeError("core_safety_reapply_failed")
        logger.debug(
            "CANONICAL_CORE_IMPORT marker=%s module=%s elapsed_ms=%.1f wrapped_import_chain_bypassed=true",
            marker,
            name,
            (time.monotonic() - started) * 1000.0,
        )
        return target

    setattr(resolve_target_v144, _PATCH_ATTR, True)
    setattr(resolve_target_v144, "__wrapped__", current)
    module._resolve_target = resolve_target_v144
    return True


def _patch_downstream_installer(module: ModuleType) -> bool:
    current = getattr(module, "install_import_hook", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def install_quiet_v144() -> None:
        state = getattr(module, "_STATE", {})
        installed = os.environ.get("NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED") == "1"
        if installed and isinstance(state, dict) and all(bool(v) for v in state.values()):
            try_patch = getattr(module, "_try_patch_loaded", None)
            if callable(try_patch):
                try_patch()
            logging.getLogger("nija.downstream_risk_governor_equity_repair").debug(
                "DOWNSTREAM_RISK_GOVERNOR_V2_HEALTHY marker=%s", getattr(module, "_MARKER", "")
            )
            return
        current()

    setattr(install_quiet_v144, _PATCH_ATTR, True)
    setattr(install_quiet_v144, "__wrapped__", current)
    module.install_import_hook = install_quiet_v144
    module.install = install_quiet_v144
    return True


def _patch_scan_installer(module: ModuleType) -> bool:
    current = getattr(module, "install", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def install_quiet_v144() -> bool:
        if os.environ.get("NIJA_SCAN_WRAPPER_CONVERGENCE_REPAIR_INSTALLED") == "1":
            guard = getattr(module, "_guard_secondary_scan_owner", None)
            patch_loaded = getattr(module, "_patch_loaded", None)
            if callable(guard):
                guard()
            if callable(patch_loaded):
                patch_loaded()
            logging.getLogger("nija.scan_wrapper_convergence_repair").debug(
                "SCAN_WRAPPER_CONVERGENCE_REPAIR_HEALTHY marker=%s", getattr(module, "_MARKER", "")
            )
            return True
        return bool(current())

    setattr(install_quiet_v144, _PATCH_ATTR, True)
    setattr(install_quiet_v144, "__wrapped__", current)
    module.install = install_quiet_v144
    return True


def _patch_runtime_manifest(module: ModuleType) -> bool:
    publish = getattr(module, "_publish", None)
    install = getattr(module, "install_import_hook", None)
    if not callable(publish) or not callable(install):
        return False

    # v144 is the terminal release owner. The v139 module class write barrier
    # uses DECLARED_RELEASE_ID, so update that canonical declaration first.
    module.DECLARED_RELEASE_ID = RELEASE_ID
    module.RELEASE_ID = RELEASE_ID
    os.environ["NIJA_RUNTIME_RELEASE_ID"] = RELEASE_ID

    if not bool(getattr(publish, _PATCH_ATTR, False)):
        original_publish = publish

        @wraps(original_publish)
        def publish_v144(ready: bool, details: dict[str, str]) -> None:
            previous = os.environ.get("NIJA_RUNTIME_RELEASE_READY", "")
            module.RELEASE_ID = RELEASE_ID
            module.DECLARED_RELEASE_ID = RELEASE_ID
            os.environ["NIJA_RUNTIME_RELEASE_ID"] = RELEASE_ID
            os.environ["NIJA_RUNTIME_RELEASE_READY"] = "1" if ready else "0"
            log = logging.getLogger("nija.runtime_release_manifest")
            if ready:
                log.info(
                    "NIJA_RUNTIME_RELEASE_MANIFEST release=%s deployment_sha=%s ready=true python_pid=%s details=%s",
                    RELEASE_ID,
                    module._deployment_sha(),
                    os.getpid(),
                    details,
                )
                if previous == "0":
                    log.warning("RUNTIME_RELEASE_CONVERGENCE_RECOVERED release=%s", RELEASE_ID)
            else:
                log.critical(
                    "NIJA_RUNTIME_RELEASE_MANIFEST release=%s deployment_sha=%s ready=false python_pid=%s details=%s",
                    RELEASE_ID,
                    module._deployment_sha(),
                    os.getpid(),
                    details,
                )
                log.critical(
                    "RUNTIME_RELEASE_INCOMPLETE_EXECUTION_UNSAFE release=%s action=keep_broker_order_gates_fail_closed",
                    RELEASE_ID,
                )

        setattr(publish_v144, _PATCH_ATTR, True)
        setattr(publish_v144, "__wrapped__", original_publish)
        module._publish = publish_v144

    if not bool(getattr(install, _PATCH_ATTR, False)):
        original_install = install
        gate_lock = threading.RLock()
        last_full_audit = {"ts": 0.0}

        @wraps(original_install)
        def install_v144() -> None:
            with gate_lock:
                now = time.monotonic()
                healthy = (
                    bool(getattr(module, "_INSTALLED", False))
                    and os.environ.get("NIJA_RUNTIME_RELEASE_READY") == "1"
                )
                try:
                    min_interval = max(
                        5.0,
                        float(os.environ.get("NIJA_RUNTIME_RELEASE_REENTRY_AUDIT_MIN_S", "30") or 30.0),
                    )
                except Exception:
                    min_interval = 30.0
                if healthy and now - last_full_audit["ts"] < min_interval:
                    logging.getLogger("nija.runtime_release_manifest").debug(
                        "RUNTIME_RELEASE_REENTRY_COALESCED release=%s", RELEASE_ID
                    )
                    return
                last_full_audit["ts"] = now
                original_install()

        setattr(install_v144, _PATCH_ATTR, True)
        setattr(install_v144, "__wrapped__", original_install)
        module.install_import_hook = install_v144

    return True


def _patch_capital_refresh(module: ModuleType) -> bool:
    cls = getattr(module, "MultiAccountBrokerManager", None)
    current = getattr(cls, "refresh_capital_authority", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def refresh_v144(self: Any, *args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        trigger = str(kwargs.get("trigger", "refresh_capital_authority") or "refresh_capital_authority")
        try:
            result = current(self, *args, **kwargs)
        except Exception as exc:
            LOGGER.error(
                "CAPITAL_REFRESH_COMPLETED marker=%s trigger=%s success=false error=%s:%s duration_ms=%.1f",
                MARKER,
                trigger,
                type(exc).__name__,
                exc,
                (time.monotonic() - started) * 1000.0,
            )
            raise
        ready = bool(result.get("ready")) if isinstance(result, dict) else bool(getattr(result, "ready", False))
        capital = 0.0
        try:
            capital = float(result.get("total_capital", 0.0) or 0.0) if isinstance(result, dict) else float(getattr(result, "total_capital", 0.0) or 0.0)
        except Exception:
            capital = 0.0
        LOGGER.info(
            "CAPITAL_REFRESH_COMPLETED marker=%s trigger=%s success=true ready=%s total_capital=%.2f duration_ms=%.1f",
            MARKER,
            trigger,
            str(ready).lower(),
            capital,
            (time.monotonic() - started) * 1000.0,
        )
        return result

    setattr(refresh_v144, _PATCH_ATTR, True)
    setattr(refresh_v144, "__wrapped__", current)
    cls.refresh_capital_authority = refresh_v144
    return True


def _patch_loaded() -> dict[str, bool]:
    results: dict[str, bool] = {}
    targets = (
        (("bot.trading_state_machine", "trading_state_machine"), _patch_trading_state_machine, "trading_state_machine"),
        (("bot.execution_pipeline", "execution_pipeline"), _patch_execution_pipeline, "execution_pipeline"),
        (("bot.nija_ai_engine", "nija_ai_engine"), _patch_ai_engine, "ai_engine"),
        (("bot.readiness_table", "readiness_table"), _patch_readiness_table, "readiness_table"),
        (("bot.canonical_core_import_handoff_v125_patch",), _patch_canonical_import_handoff, "canonical_import"),
        (("bot.downstream_risk_governor_equity_repair_patch",), _patch_downstream_installer, "downstream_installer"),
        (("scan_wrapper_convergence_repair_patch", "nija.scan_wrapper_convergence_repair_patch"), _patch_scan_installer, "scan_installer"),
        (("bot.runtime_release_manifest_patch",), _patch_runtime_manifest, "runtime_manifest"),
        (("bot.multi_account_broker_manager", "multi_account_broker_manager"), _patch_capital_refresh, "capital_refresh"),
    )
    for names, patcher, label in targets:
        result = False
        seen: set[int] = set()
        for name in names:
            module = sys.modules.get(name)
            if not isinstance(module, ModuleType) or id(module) in seen:
                continue
            seen.add(id(module))
            try:
                result = bool(patcher(module)) or result
            except Exception as exc:
                LOGGER.exception(
                    "RUNTIME_QUALITY_V144_PATCH_FAILED marker=%s target=%s module=%s error=%s",
                    MARKER,
                    label,
                    name,
                    exc,
                )
        results[label] = result
    return results


def _critical_ready(results: dict[str, bool]) -> bool:
    # These are the safety-critical live-entry controls. Observability/noise
    # patches may attach later as their modules naturally load.
    return bool(results.get("trading_state_machine") and results.get("execution_pipeline"))


def _monitor() -> None:
    deadline = time.monotonic() + max(
        60.0,
        float(os.environ.get("NIJA_RUNTIME_QUALITY_V144_MONITOR_S", "600") or 600.0),
    )
    last: dict[str, bool] = {}
    while time.monotonic() < deadline:
        try:
            results = _patch_loaded()
            if results != last:
                last = results
                LOGGER.info("RUNTIME_QUALITY_V144_PROGRESS marker=%s targets=%s", MARKER, results)
            if _critical_ready(results):
                os.environ[_READY_FLAG] = "1"
            # Keep watching because execution/capital/AI modules can load after
            # activation. Every patcher is idempotent.
        except Exception as exc:
            LOGGER.exception("RUNTIME_QUALITY_V144_MONITOR_ERROR marker=%s error=%s", MARKER, exc)
        time.sleep(0.25)


def install_import_hook() -> bool:
    global _INSTALLED, _MONITOR_STARTED
    with _LOCK:
        results = _patch_loaded()
        if not _MONITOR_STARTED:
            _MONITOR_STARTED = True
            threading.Thread(target=_monitor, name="RuntimeQualityHardeningV144", daemon=True).start()
        os.environ[_FLAG] = "1"
        if _critical_ready(results):
            os.environ[_READY_FLAG] = "1"
        else:
            os.environ.setdefault(_READY_FLAG, "0")
        _INSTALLED = True
        LOGGER.info(
            "RUNTIME_QUALITY_HARDENING_V144_INSTALLED marker=%s release=%s targets=%s strict_reconciliation=true live_ai_gate_required=true exits_unaffected=true",
            MARKER,
            RELEASE_ID,
            results,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_reconciliation_status",
    "_entry_increases_exposure",
    "_patch_trading_state_machine",
    "_patch_execution_pipeline",
    "_patch_ai_engine",
    "_patch_readiness_table",
    "_patch_canonical_import_handoff",
    "_patch_downstream_installer",
    "_patch_scan_installer",
    "_patch_runtime_manifest",
    "_patch_capital_refresh",
    "_patch_loaded",
]
