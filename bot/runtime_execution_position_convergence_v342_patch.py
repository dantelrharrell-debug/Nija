"""Runtime position-proof convergence hardening v342.

Production generation 5096 exposed three fail-closed liveness/integrity gaps:

* Coinbase ``get_positions`` runs inside v117's bounded single-flight, but its
  internal API helper may perform several retries with multi-second backoff.
  Those nested retries can outlive the outer authoritative-position deadline,
  leaving v117 generations to time out/supersede even when the broker is alive.
* Kraken v287 intentionally allows live authoritative Balance workers a large
  rate-profile budget.  A MICRO_CAP worker can therefore remain registered for
  roughly three monitoring intervals even when it has made no useful progress,
  keeping platform position proof false and starving capital refresh workers.
* v239 synthesizes TP1/TP2/TP3 from any positive tracker entry price.  A stale or
  corrupted cost basis can therefore create nonsensical profit targets before
  authoritative position truth catches up.

v342 preserves fail-closed behavior.  It does not mark any broker synchronized,
extend snapshot freshness, fabricate positions/cost basis/execution proof, raise
thread caps, bypass minimum-notional/risk/nonce/writer/kill-switch gates, or force
orders.  It only bounds nested Coinbase retries during position reads, tightens
Kraken live-flight age to one expected rate interval plus explicit headroom, and
blocks *newly synthesized* profit targets when cost-basis sanity cannot be proven.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_execution_position_convergence_v342")
MARKER = "20260901-runtime-execution-position-convergence-v342"
RELEASE_ID = "20260901-runtime-convergence-v342"
_READY_FLAG = "NIJA_RUNTIME_EXECUTION_POSITION_CONVERGENCE_V342_READY"
_IMPORT_HOOK_FLAG = "_NIJA_RUNTIME_EXECUTION_POSITION_CONVERGENCE_V342_IMPORT_HOOK"
_COINBASE_ATTR = "_nija_coinbase_position_retry_budget_v342"
_KRAKEN_ATTR = "_nija_kraken_position_progress_deadline_v342"
_PROFIT_ATTR = "_nija_profit_target_cost_basis_sanity_v342"
_LOCK = threading.RLock()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return default if number != number else number
    except Exception:
        return default


def _truthy(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _chain_has(callable_obj: Any, attr: str) -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(64):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        if bool(getattr(current, attr, False)):
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _coinbase_position_call_context() -> bool:
    """Return True only while Coinbase's raw position reader is on this stack."""
    try:
        frame = sys._getframe(1)
    except Exception:
        return False
    for _ in range(48):
        if frame is None:
            break
        name = str(getattr(getattr(frame, "f_code", None), "co_name", "") or "").lower()
        module = str(getattr(frame, "f_globals", {}).get("__name__", "") or "").lower()
        if name == "get_positions" and module.endswith("broker_manager"):
            return True
        frame = getattr(frame, "f_back", None)
    return False


def _patch_coinbase_retry_budget(module: ModuleType) -> bool:
    cls = getattr(module, "CoinbaseBroker", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_api_call_with_retry", None)
    if not callable(current):
        return False
    if _chain_has(current, _COINBASE_ATTR):
        return True
    original = current

    @wraps(original)
    def api_call_with_retry_v342(self: Any, api_func: Any, *args: Any, **kwargs: Any):
        if not _coinbase_position_call_context():
            return original(self, api_func, *args, **kwargs)

        requested_retries = kwargs.pop("max_retries", 3)
        requested_delay = kwargs.pop("base_delay", 5.0)
        try:
            requested_retries_i = max(1, int(requested_retries))
        except Exception:
            requested_retries_i = 3
        delay_cap = max(0.0, min(1.0, _f(os.environ.get("NIJA_COINBASE_POSITION_RETRY_BASE_DELAY_S"), 0.25)))
        requested_delay_f = max(0.0, _f(requested_delay, 5.0))
        effective_delay = min(requested_delay_f, delay_cap)

        LOGGER.info(
            "COINBASE_POSITION_RETRY_BUDGET_V342 marker=%s requested_retries=%d effective_retries=1 "
            "requested_base_delay_s=%.2f effective_base_delay_s=%.2f outer_v117_authority_unchanged=true "
            "ordinary_coinbase_api_retries_unchanged=true synthetic_success=false safety_gates_bypassed=false",
            MARKER,
            requested_retries_i,
            requested_delay_f,
            effective_delay,
        )
        return original(
            self,
            api_func,
            *args,
            max_retries=1,
            base_delay=effective_delay,
            **kwargs,
        )

    setattr(api_call_with_retry_v342, _COINBASE_ATTR, True)
    setattr(api_call_with_retry_v342, "__wrapped__", original)
    cls._api_call_with_retry = api_call_with_retry_v342
    return True


def _kraken_progress_budget_s(module: ModuleType, flight: Mapping[str, Any]) -> float:
    broker = flight.get("broker") if isinstance(flight, Mapping) else None
    interval_fn = getattr(module, "_monitoring_interval_s", None)
    try:
        interval = max(0.0, float(interval_fn(broker) or 0.0)) if callable(interval_fn) else 0.0
    except Exception:
        interval = 0.0
    configured = max(
        45.0,
        min(
            180.0,
            _f(os.environ.get("NIJA_KRAKEN_POSITION_PROGRESS_MAX_AGE_S"), 90.0),
        ),
    )
    grace = max(
        15.0,
        min(
            60.0,
            _f(os.environ.get("NIJA_KRAKEN_POSITION_PROGRESS_GRACE_S"), 30.0),
        ),
    )
    # A legitimate pre-wait may consume one full monitoring interval.  Give it
    # explicit headroom for lock admission + HTTP completion, but not another
    # two full rate intervals as the older 3x policy did.
    return min(240.0, max(configured, interval + grace))


def _patch_kraken_flight_deadline(module: ModuleType) -> bool:
    current = getattr(module, "_flight_hard_age_s", None)
    if not callable(current):
        return False
    if _chain_has(current, _KRAKEN_ATTR):
        return True
    original = current

    @wraps(original)
    def flight_hard_age_v342(flight: dict[str, Any]) -> float:
        legacy = max(30.0, _f(original(flight), 90.0))
        progress_budget = _kraken_progress_budget_s(module, flight)
        bounded = max(30.0, min(legacy, progress_budget))
        return bounded

    setattr(flight_hard_age_v342, _KRAKEN_ATTR, True)
    setattr(flight_hard_age_v342, "__wrapped__", original)
    module._flight_hard_age_s = flight_hard_age_v342
    return True


def _row_entry(row: Mapping[str, Any]) -> float:
    for key in (
        "entry_price",
        "avg_entry_price",
        "average_entry_price",
        "average_price",
        "cost_basis_price",
        "avg_price",
    ):
        value = _f(row.get(key))
        if value > 0.0:
            return value
    return 0.0


def _row_quantity(row: Mapping[str, Any]) -> float:
    for key in ("quantity", "qty", "size", "amount", "units", "balance"):
        if row.get(key) is not None:
            return abs(_f(row.get(key)))
    return 0.0


def _row_market_price(row: Mapping[str, Any]) -> float:
    for key in ("current_price", "market_price", "last_price", "mark_price", "price"):
        value = _f(row.get(key))
        if value > 0.0:
            return value
    qty = _row_quantity(row)
    if qty <= 0.0:
        return 0.0
    for key in ("market_value", "current_value", "position_value", "size_usd", "notional"):
        total = abs(_f(row.get(key)))
        if total > 0.0:
            return total / qty
    return 0.0


def _explicit_target_present(row: Mapping[str, Any]) -> bool:
    return any(
        _f(row.get(key)) > 0.0
        for key in ("take_profit", "take_profit_1", "take_profit_2", "take_profit_3", "profit_target")
    )


def _freshness_reason(row: Mapping[str, Any]) -> str:
    for key in ("authoritative_snapshot_stale", "snapshot_stale", "position_snapshot_stale"):
        if row.get(key) is True:
            return key
    for key in ("authoritative_snapshot_ready", "snapshot_ready", "position_snapshot_ready"):
        if key in row and row.get(key) is False:
            return key
    age = _f(row.get("snapshot_age_s"), -1.0)
    max_age = _f(row.get("snapshot_max_age_s"), 0.0)
    if age >= 0.0 and max_age > 0.0 and age > max_age:
        return f"snapshot_age_s={age:.1f}>max_age_s={max_age:.1f}"
    return ""


def _cost_basis_sanity(row: Mapping[str, Any]) -> tuple[bool, str, float, float]:
    if row.get("cost_basis_verified") is False:
        return False, "cost_basis_explicitly_unverified", 0.0, 0.0
    if bool(row.get("auto_exit_blocked", False)):
        return False, "auto_exit_blocked", 0.0, 0.0
    freshness = _freshness_reason(row)
    if freshness:
        return False, freshness, 0.0, 0.0

    entry = _row_entry(row)
    qty = _row_quantity(row)
    if entry <= 0.0 or qty <= 0.0:
        return False, "missing_entry_or_quantity", entry, 0.0

    market = _row_market_price(row)
    if market <= 0.0:
        if _truthy("NIJA_PROFIT_TARGET_REQUIRE_MARKET_SANITY", True):
            return False, "market_price_unavailable", entry, market
        return True, "market_sanity_disabled", entry, market

    ratio = max(entry / market, market / entry)
    max_ratio = max(
        2.0,
        min(
            50.0,
            _f(os.environ.get("NIJA_PROFIT_TARGET_ENTRY_MARKET_MAX_RATIO"), 8.0),
        ),
    )
    if ratio > max_ratio:
        return False, f"entry_market_ratio={ratio:.3f}>max_ratio={max_ratio:.3f}", entry, market
    return True, "entry_market_sane", entry, market


def _patch_profit_target_sanity(module: ModuleType) -> bool:
    current = getattr(module, "_with_profit_targets", None)
    if not callable(current):
        return False
    if _chain_has(current, _PROFIT_ATTR):
        return True
    original = current

    @wraps(original)
    def with_profit_targets_v342(raw: Any) -> Any:
        if not isinstance(raw, Mapping):
            return original(raw)
        row = dict(raw)
        # Explicit pre-existing targets belong to their existing provenance and
        # are preserved.  v342 only governs *new synthesis* by v239.
        if _explicit_target_present(row):
            return original(row)
        sane, reason, entry, market = _cost_basis_sanity(row)
        if not sane:
            LOGGER.warning(
                "PROFIT_TARGET_SYNTHESIS_V342_BLOCKED marker=%s account=%s symbol=%s reason=%s "
                "entry=%.8f market=%.8f existing_targets_preserved=true stop_loss_unchanged=true "
                "trailing_profit_unchanged=true order_submitted=false synthetic_target=false "
                "position_truth_fabricated=false safety_gates_bypassed=false",
                MARKER,
                str(row.get("account_id") or row.get("user_id") or row.get("account") or "platform"),
                str(row.get("symbol") or "unknown"),
                reason,
                entry,
                market,
            )
            return row
        return original(row)

    setattr(with_profit_targets_v342, _PROFIT_ATTR, True)
    setattr(with_profit_targets_v342, "__wrapped__", original)
    module._with_profit_targets = with_profit_targets_v342
    return True


def _patch_v320_idempotency(module: ModuleType) -> bool:
    """Harden the v323 adapter against terminal wrappers added after installation."""
    current = getattr(module, "_patch_v285_platform_refresh", None)
    refresh_attr = str(getattr(module, "_REFRESH_PATCH_ATTR", "_nija_platform_position_proactive_refresh_v323"))
    if not callable(current):
        return False
    if bool(getattr(current, "_nija_v342_idempotency_guard", False)):
        return True
    original = current

    @wraps(original)
    def patch_v285_platform_refresh_v342(v285_module: ModuleType) -> bool:
        candidate = getattr(v285_module, "_platform_candidates", None)
        if _chain_has(candidate, refresh_attr):
            return True
        return bool(original(v285_module))

    setattr(patch_v285_platform_refresh_v342, "_nija_v342_idempotency_guard", True)
    setattr(patch_v285_platform_refresh_v342, "__wrapped__", original)
    module._patch_v285_platform_refresh = patch_v285_platform_refresh_v342
    return True


def _patch_module(name: str, module: ModuleType) -> bool:
    changed = False
    if name in {"bot.broker_manager", "broker_manager"}:
        changed = _patch_coinbase_retry_budget(module) or changed
    if name in {
        "bot.runtime_kraken_position_flight_recovery_v287_patch",
        "runtime_kraken_position_flight_recovery_v287_patch",
    }:
        changed = _patch_kraken_flight_deadline(module) or changed
    if name in {
        "bot.runtime_all_account_profit_targets_v239_patch",
        "runtime_all_account_profit_targets_v239_patch",
    }:
        changed = _patch_profit_target_sanity(module) or changed
    if name in {
        "bot.runtime_platform_position_sync_isolation_v320_patch",
        "runtime_platform_position_sync_isolation_v320_patch",
    }:
        changed = _patch_v320_idempotency(module) or changed
    return changed


def _patch_loaded() -> dict[str, bool]:
    outcomes = {
        "coinbase_retry_budget": False,
        "kraken_flight_deadline": False,
        "profit_target_sanity": False,
        "v320_idempotency": False,
    }
    aliases = (
        ("coinbase_retry_budget", ("bot.broker_manager", "broker_manager")),
        (
            "kraken_flight_deadline",
            ("bot.runtime_kraken_position_flight_recovery_v287_patch", "runtime_kraken_position_flight_recovery_v287_patch"),
        ),
        (
            "profit_target_sanity",
            ("bot.runtime_all_account_profit_targets_v239_patch", "runtime_all_account_profit_targets_v239_patch"),
        ),
        (
            "v320_idempotency",
            ("bot.runtime_platform_position_sync_isolation_v320_patch", "runtime_platform_position_sync_isolation_v320_patch"),
        ),
    )
    for key, names in aliases:
        seen: set[int] = set()
        for name in names:
            module = sys.modules.get(name)
            if not isinstance(module, ModuleType) or id(module) in seen:
                continue
            seen.add(id(module))
            try:
                outcomes[key] = bool(_patch_module(name, module)) or outcomes[key]
            except Exception as exc:
                LOGGER.error(
                    "RUNTIME_POSITION_V342_PATCH_ERROR marker=%s surface=%s error=%s:%s fail_closed=true",
                    MARKER,
                    key,
                    type(exc).__name__,
                    exc,
                )
    return outcomes


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_execution_position_convergence_v342"] = _READY_FLAG
        return True
    except Exception:
        # The manifest may not exist yet when executable_trade_runtime_patch is
        # installed.  The import hook will re-run registration when it appears.
        return True


def _install_import_hook() -> bool:
    if bool(getattr(builtins, _IMPORT_HOOK_FLAG, False)):
        return True
    original_import = builtins.__import__

    @wraps(original_import)
    def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        result = original_import(name, globals, locals, fromlist, level)
        text = str(name or "")
        if any(
            token in text
            for token in (
                "broker_manager",
                "runtime_kraken_position_flight_recovery_v287",
                "runtime_all_account_profit_targets_v239",
                "runtime_platform_position_sync_isolation_v320",
                "runtime_release_manifest",
            )
        ):
            _patch_loaded()
            if "runtime_release_manifest" in text:
                _register_manifest()
        return result

    builtins.__import__ = importing
    setattr(builtins, _IMPORT_HOOK_FLAG, True)
    return True


def install() -> bool:
    with _LOCK:
        manifest_ok = _register_manifest()
        hook_ok = _install_import_hook()
        outcomes = _patch_loaded()
        # A surface may not be imported yet; the hook is the readiness contract
        # for deferred installation.  Never claim broker/position readiness here.
        ready = bool(manifest_ok and hook_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        LOGGER.critical(
            "RUNTIME_EXECUTION_POSITION_CONVERGENCE_V342_%s marker=%s ready=%s outcomes=%s "
            "coinbase_nested_position_retries_bounded=true kraken_progress_deadline_bounded=true "
            "profit_target_sanity_required=true v320_wrapper_idempotency_hardened=true "
            "capital_thread_cap_unchanged=true snapshot_ttl_unchanged=true position_success_fabricated=false "
            "execution_proof_fabricated=false forced_trade=false forced_activation=false "
            "writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY",
            MARKER,
            str(ready).lower(),
            outcomes,
        )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_patch_coinbase_retry_budget",
    "_patch_kraken_flight_deadline",
    "_patch_profit_target_sanity",
    "_patch_v320_idempotency",
    "_cost_basis_sanity",
    "_coinbase_position_call_context",
    "_kraken_progress_budget_s",
]
