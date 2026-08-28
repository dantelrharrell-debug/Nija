"""Require a live protective-exit stack before NIJA adds new exposure (v265).

This hotfix addresses a production safety failure mode where entries can exist
while stop-loss / take-profit / trailing protection is not actually able to
submit a close.  The existing exit engines remain authoritative; v265 only
reasserts them, repairs Kraken close intent, and fail-closes *new entries* when
that protection stack cannot be proven ready.

Safety contract
---------------
* Existing exit/reduce requests are never blocked by this guard.
* Kraken protective sells are tagged intent_type=exit + position_effect=close
  and preserve the exact account adapter/account id.
* Mere order acknowledgement is not treated as a confirmed protective exit.
* No cost basis, market price, fill, PnL, readiness or execution proof is
  fabricated.
* Writer, nonce, risk, capital, broker-health, ECEL, minimum-notional and fill
  gates remain authoritative.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_protective_exit_authority_v265")
MARKER = "20260828-protective-exit-authority-v265"
_READY_FLAG = "NIJA_PROTECTIVE_EXIT_AUTHORITY_V265_READY"
_PIPELINE_PATCH_ATTR = "_nija_protective_exit_authority_v265"
_KRAKEN_SUBMIT_PATCH_ATTR = "_nija_protective_exit_submit_v265"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None

_FILL_LIKE = {"filled", "closed", "done", "complete", "completed", "success", "settled"}


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled", "y"}


def _is_exit_request(request: Any) -> bool:
    intent = str(getattr(request, "intent_type", "") or "").strip().lower()
    effect = str(getattr(request, "position_effect", "") or "").strip().lower()
    metadata = dict(getattr(request, "metadata", {}) or {})
    return (
        intent in {"exit", "reduce"}
        or effect in {"close", "reduce"}
        or metadata.get("closing_position") is True
    )


def _filled_result(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    status = str(payload.get("status") or payload.get("state") or "").strip().lower()
    if status in _FILL_LIKE:
        return True
    try:
        filled = max(
            float(payload.get("filled_size") or 0.0),
            float(payload.get("filled_qty") or 0.0),
            float(payload.get("filled_quantity") or 0.0),
            float(payload.get("executed_qty") or 0.0),
            float(payload.get("filled_size_usd") or 0.0),
        )
    except Exception:
        filled = 0.0
    return filled > 0.0 and status not in {
        "error", "failed", "rejected", "cancelled", "canceled", "expired", "unfilled"
    }


def _install_module(module_name: str) -> tuple[bool, ModuleType | None, str]:
    try:
        module = importlib.import_module(module_name)
        installer = getattr(module, "install_import_hook", None)
        if not callable(installer):
            installer = getattr(module, "install", None)
        if callable(installer):
            result = installer()
            if result is False:
                return False, module, "installer_returned_false"
        return True, module, "ok"
    except Exception as exc:
        return False, None, f"{type(exc).__name__}:{exc}"


def _patch_kraken_exit_submit(module: ModuleType) -> bool:
    current = getattr(module, "_submit_exit", None)
    if not callable(current):
        return False
    if bool(getattr(current, _KRAKEN_SUBMIT_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def submit_exit_v265(
        broker: Any,
        account: str,
        pair: str,
        quantity: float,
        reason: str,
    ) -> Mapping[str, Any]:
        try:
            from bot.pipeline_order_submitter import submit_market_order_via_pipeline

            result = submit_market_order_via_pipeline(
                broker=broker,
                symbol=pair,
                side="sell",
                quantity=quantity,
                size_type="base",
                strategy=f"KrakenAccountExit:{reason}",
                intent_type="exit",
                account_id_override=account,
                position_effect="close",
                metadata_override={
                    "closing_position": True,
                    "protective_exit": True,
                    "exit_reason": str(reason or ""),
                    "protective_exit_marker": MARKER,
                },
            )
        except Exception as exc:
            return {
                "status": "error",
                "error": f"protective_exit_submit_exception:{type(exc).__name__}:{exc}",
            }

        if not isinstance(result, Mapping):
            return {"status": "error", "error": f"protective_exit_invalid_result:{result}"}

        output = dict(result)
        if _filled_result(output):
            LOGGER.critical(
                "PROTECTIVE_EXIT_V265_KRAKEN_FILL marker=%s account=%s pair=%s reason=%s "
                "intent=exit position_effect=close fill_confirmed=true",
                MARKER,
                account,
                pair,
                reason,
            )
            return output

        # The legacy Kraken account scanner treats any order_id / 'accepted'
        # response as closed.  Convert non-fill acknowledgements to a terminally
        # unconfirmed result so it leaves the position tracked and retries after
        # reconciliation instead of falsely removing its protection.
        pending_id = output.get("order_id") or output.get("id") or output.get("txid")
        LOGGER.error(
            "PROTECTIVE_EXIT_V265_KRAKEN_UNCONFIRMED marker=%s account=%s pair=%s reason=%s "
            "status=%s order_id=%s position_remains_open=true",
            MARKER,
            account,
            pair,
            reason,
            output.get("status") or output.get("state") or "unknown",
            pending_id or "missing",
        )
        return {
            "status": "error",
            "error": "protective_exit_not_fill_confirmed",
            "pending_order_id": pending_id,
            "raw_status": output.get("status") or output.get("state"),
        }

    setattr(submit_exit_v265, _KRAKEN_SUBMIT_PATCH_ATTR, True)
    setattr(submit_exit_v265, "__wrapped__", current)
    module._submit_exit = submit_exit_v265
    return True


def _stack_truth() -> tuple[bool, dict[str, Any]]:
    universal = sys.modules.get("bot.universal_broker_exit_supervisor_patch")
    live_v25 = sys.modules.get("bot.live_broker_profit_exit_convergence_v25")
    kraken_exit = sys.modules.get("bot.kraken_all_account_exit_runtime_patch")
    v75 = sys.modules.get("bot.held_position_exit_bootstrap_v75_patch")

    universal_started = bool(
        isinstance(universal, ModuleType)
        and isinstance(getattr(universal, "_STATE", None), dict)
        and getattr(universal, "_STATE").get("started") is True
    )
    live_reconciler = bool(isinstance(live_v25, ModuleType) and getattr(live_v25, "_RECONCILER_STARTED", False))
    kraken_submit = getattr(kraken_exit, "_submit_exit", None) if isinstance(kraken_exit, ModuleType) else None
    kraken_patched = bool(callable(kraken_submit) and getattr(kraken_submit, _KRAKEN_SUBMIT_PATCH_ATTR, False))
    held_bootstrap = bool(
        isinstance(v75, ModuleType)
        and _truthy(os.environ.get("NIJA_HELD_POSITION_EXIT_BOOTSTRAP_V75_INSTALLED"))
    )
    targets = _truthy(os.environ.get("NIJA_ALL_ACCOUNT_PROFIT_TARGETS_V239_READY"))
    auto_exit_enabled = _truthy(os.environ.get("NIJA_AUTO_EXIT_SL_TP_ENABLED", "true"))
    trailing_tp = _truthy(os.environ.get("NIJA_TRAILING_TP_ENABLED", "true"))
    trailing_stop = _truthy(os.environ.get("NIJA_TRAILING_STOP_ENABLED", "true"))

    details = {
        "universal_started": universal_started,
        "live_reconciler": live_reconciler,
        "kraken_exit_context": kraken_patched,
        "held_bootstrap": held_bootstrap,
        "profit_targets": targets,
        "auto_exit": auto_exit_enabled,
        "trailing_tp": trailing_tp,
        "trailing_stop": trailing_stop,
    }
    return all(details.values()), details


def _patch_execution_pipeline() -> bool:
    try:
        module = importlib.import_module("bot.execution_pipeline")
    except Exception:
        return False
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "execute", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PIPELINE_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def execute_v265(self: Any, request: Any):
        if _is_exit_request(request):
            return current(self, request)
        if _truthy(os.environ.get(_READY_FLAG)):
            return current(self, request)

        result_cls = getattr(module, "PipelineResult", None)
        if not isinstance(result_cls, type):
            # Do not risk calling into an entry path when the safety result type
            # is unavailable. Raising is fail-closed and keeps exits unaffected.
            raise RuntimeError("ProtectiveExitAuthority unavailable: new exposure blocked")
        size = getattr(request, "size_usd", None)
        if size is None:
            size = getattr(request, "notional_usd", 0.0)
        LOGGER.critical(
            "PROTECTIVE_EXIT_V265_ENTRY_BLOCKED marker=%s symbol=%s side=%s "
            "reason=protective_exit_stack_not_ready exits_still_allowed=true trading_fail_closed=true",
            MARKER,
            getattr(request, "symbol", ""),
            getattr(request, "side", ""),
        )
        return result_cls(
            success=False,
            symbol=str(getattr(request, "symbol", "") or ""),
            side=str(getattr(request, "side", "") or ""),
            size_usd=float(size or 0.0),
            error="ProtectiveExitAuthority deny: protective exit stack unavailable",
        )

    setattr(execute_v265, _PIPELINE_PATCH_ATTR, True)
    setattr(execute_v265, "__wrapped__", current)
    cls.execute = execute_v265
    return True


def reassert() -> bool:
    """Install/reassert existing protection engines without weakening their gates."""
    with _LOCK:
        outcomes: dict[str, str] = {}
        order = (
            "bot.auto_exit_sl_tp_runtime_patch",
            "bot.universal_broker_exit_supervisor_patch",
            "bot.live_broker_profit_exit_convergence_v25",
            "bot.kraken_all_account_exit_runtime_patch",
            "bot.adaptive_profit_exit_v74_patch",
            "bot.held_position_exit_bootstrap_v75_patch",
        )
        loaded: dict[str, ModuleType] = {}
        for name in order:
            ok, module, detail = _install_module(name)
            outcomes[name] = "ok" if ok else detail
            if module is not None:
                loaded[name] = module

        kraken_module = loaded.get("bot.kraken_all_account_exit_runtime_patch")
        kraken_patch = bool(kraken_module and _patch_kraken_exit_submit(kraken_module))
        pipeline_patch = _patch_execution_pipeline()
        stack_ready, details = _stack_truth()
        ready = bool(stack_ready and kraken_patch and pipeline_patch and all(value == "ok" for value in outcomes.values()))
        os.environ[_READY_FLAG] = "1" if ready else "0"

        log = LOGGER.critical if ready else LOGGER.error
        log(
            "PROTECTIVE_EXIT_AUTHORITY_V265_%s marker=%s ready=%s stack=%s outcomes=%s "
            "entry_fail_closed=true exits_always_allowed=true kraken_explicit_exit_context=%s "
            "fill_confirmation_required=true stop_loss_preserved=true take_profit_preserved=true "
            "trailing_take_profit_preserved=true trailing_stop_preserved=true cost_basis_fabricated=false "
            "price_fabricated=false forced_exit=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY",
            MARKER,
            str(ready).lower(),
            details,
            outcomes,
            str(kraken_patch).lower(),
        )
        return ready


def _worker() -> None:
    while True:
        try:
            reassert()
        except Exception as exc:
            os.environ[_READY_FLAG] = "0"
            LOGGER.exception(
                "PROTECTIVE_EXIT_V265_REASSERT_FAILED marker=%s error=%s:%s new_entries_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
        time.sleep(max(3.0, float(os.environ.get("NIJA_PROTECTIVE_EXIT_REASSERT_SECONDS", "5") or 5.0)))


def install() -> bool:
    global _THREAD
    ready = reassert()
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(
                target=_worker,
                name="ProtectiveExitAuthorityV265",
                daemon=True,
            )
            _THREAD.start()
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "reassert",
    "_filled_result",
    "_is_exit_request",
    "_patch_kraken_exit_submit",
]
