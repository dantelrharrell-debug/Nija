"""Bounded post-core activation convergence budget repair v172.

Production on 2026-08-20 showed the canonical runtime exiting fail closed while
Kraken was still completing a legitimate authenticated capital recovery.  The
capital pipeline is explicitly allowed a bounded 50-80 second convergence
window, but ``bot_main._perform_post_core_activation_convergence`` hard-capped
its activation retry loop at 30 seconds.  That orchestration mismatch could
terminate a healthy writer/core process before a fresh complete publication had
an opportunity to arrive.

v172 changes only that wait budget.  It does not make activation succeed, does
not alter ``commit_activation()``, ``can_execute()``, capital freshness, broker
connectivity, writer/nonce authority, kill switches, risk checks, order gates,
or signal thresholds.  The final gate remains fail closed exactly as before.

The repaired wait is finite and capped below the canonical 90-second capital
freshness TTL.  A stale/partial publication is still rejected by v170/v135 and
cannot become executable merely because the caller waits longer.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import os
import textwrap
import threading
from types import FunctionType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_post_core_activation_budget_v172")
MARKER = "20260820-runtime-post-core-activation-budget-v172"
_READY_FLAG = "NIJA_RUNTIME_POST_CORE_ACTIVATION_BUDGET_V172_READY"
_PATCH_ATTR = "_nija_runtime_post_core_activation_budget_v172"
_LOCK = threading.RLock()

_DEFAULT_CAPITAL_PIPELINE_DEADLINE_S = 80.0
_DEFAULT_FRESHNESS_TTL_S = 90.0
_DEFAULT_SAFETY_MARGIN_S = 5.0
_MIN_WAIT_S = 30.0


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return float(default)


def _activation_wait_seconds(requested_timeout_s: Any = 60.0) -> float:
    """Return a finite activation wait aligned with the capital pipeline.

    The result is never allowed to reach the capital freshness TTL.  This is a
    caller wait budget only; it does not change publication timestamps/expiry.
    """
    try:
        requested = max(_MIN_WAIT_S, float(requested_timeout_s or 0.0))
    except (TypeError, ValueError):
        requested = 60.0

    pipeline_candidates = [
        _DEFAULT_CAPITAL_PIPELINE_DEADLINE_S,
        _float_env("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", 0.0),
        _float_env("NIJA_CAPITAL_PIPELINE_DEADLINE_S", 0.0),
        _float_env("NIJA_CAPITAL_RUNTIME_DEADLINE_S", 0.0),
        _float_env("NIJA_CAPITAL_REFRESH_PIPELINE_DEADLINE_S", 0.0),
    ]
    pipeline_deadline = max(float(value or 0.0) for value in pipeline_candidates)

    freshness_ttl = max(
        10.0,
        _float_env("NIJA_CAPITAL_FRESHNESS_TTL_S", _DEFAULT_FRESHNESS_TTL_S),
    )
    safety_margin = max(
        2.0,
        _float_env("NIJA_POST_CORE_ACTIVATION_FRESHNESS_MARGIN_S", _DEFAULT_SAFETY_MARGIN_S),
    )
    hard_ceiling = max(_MIN_WAIT_S, freshness_ttl - safety_margin)

    configured = _float_env("NIJA_POST_CORE_ACTIVATION_WAIT_S", 0.0)
    desired = max(requested, pipeline_deadline + safety_margin)
    if configured > 0.0:
        desired = max(desired, configured)

    return max(_MIN_WAIT_S, min(desired, hard_ceiling))


def _compile_repaired_function(target: FunctionType) -> FunctionType:
    source_lines, start_line = inspect.getsourcelines(target)
    source = textwrap.dedent("".join(source_lines))
    old = "_act_deadline = time.time() + min(timeout_s, 30.0)"
    new = "_act_deadline = time.time() + _nija_v172_activation_wait_s(timeout_s)"
    if source.count(old) != 1:
        raise RuntimeError(
            "post-core activation deadline signature changed; "
            f"expected exactly one {old!r}, found {source.count(old)}"
        )
    repaired = source.replace(old, new, 1)
    padded = ("\n" * max(0, start_line - 1)) + repaired
    namespace: dict[str, Any] = {}
    code = compile(padded, target.__code__.co_filename, "exec")
    exec(code, target.__globals__, namespace)
    replacement = namespace.get(target.__name__)
    if not isinstance(replacement, FunctionType):
        raise RuntimeError("recompiled post-core convergence function missing")
    if replacement.__code__.co_freevars != target.__code__.co_freevars:
        raise RuntimeError("post-core convergence closure contract changed")
    return replacement


def _patch_bot_main() -> bool:
    try:
        module = importlib.import_module("bot.bot_main")
    except Exception as exc:
        LOGGER.error(
            "POST_CORE_ACTIVATION_V172_IMPORT_FAILED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    target = getattr(module, "_perform_post_core_activation_convergence", None)
    if not isinstance(target, FunctionType):
        return False
    if bool(getattr(target, _PATCH_ATTR, False)):
        return True

    # Inject only the pure wait-budget helper used by the repaired code.  All
    # activation/readiness functions remain the originals from bot_main.
    target.__globals__["_nija_v172_activation_wait_s"] = _activation_wait_seconds
    try:
        replacement = _compile_repaired_function(target)
    except Exception as exc:
        LOGGER.critical(
            "POST_CORE_ACTIVATION_V172_SOURCE_REPAIR_FAILED marker=%s error=%s:%s "
            "trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    target.__code__ = replacement.__code__
    target.__defaults__ = replacement.__defaults__
    target.__kwdefaults__ = replacement.__kwdefaults__
    target.__annotations__ = dict(getattr(replacement, "__annotations__", {}) or {})
    setattr(target, _PATCH_ATTR, True)

    LOGGER.critical(
        "POST_CORE_ACTIVATION_BUDGET_V172_PATCHED marker=%s wait_s=%.1f "
        "capital_pipeline_deadline_s=%.1f freshness_ttl_s=%.1f "
        "commit_activation_unchanged=true can_execute_unchanged=true "
        "freshness_extended=false execution_bypass=false",
        MARKER,
        _activation_wait_seconds(60.0),
        max(
            _DEFAULT_CAPITAL_PIPELINE_DEADLINE_S,
            _float_env("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", 0.0),
            _float_env("NIJA_CAPITAL_PIPELINE_DEADLINE_S", 0.0),
        ),
        max(10.0, _float_env("NIJA_CAPITAL_FRESHNESS_TTL_S", _DEFAULT_FRESHNESS_TTL_S)),
    )
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_post_core_activation_budget_v172"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        bot_main_ok = _patch_bot_main()
        manifest_ok = _patch_release_manifest()
        ready = bool(bot_main_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_POST_CORE_ACTIVATION_BUDGET_V172_FAILED marker=%s bot_main=%s "
                "manifest=%s trading_fail_closed=true",
                MARKER,
                str(bot_main_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_POST_CORE_ACTIVATION_BUDGET_V172 marker=%s ready=true wait_s=%.1f "
            "finite_wait=true below_freshness_ttl=true capital_ttl_unchanged=true "
            "commit_activation_unchanged=true can_execute_unchanged=true forced_activation=false "
            "writer_nonce_risk_order_gates_unchanged=true",
            MARKER,
            _activation_wait_seconds(60.0),
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_activation_wait_seconds",
    "_patch_bot_main",
]
