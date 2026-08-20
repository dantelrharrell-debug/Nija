"""Bounded post-core activation convergence budget repair v172.

Production on 2026-08-20 showed the canonical runtime exiting fail closed while
Kraken was still completing a legitimate authenticated capital recovery. The
capital pipeline is explicitly allowed a bounded 50-80 second convergence
window, while historical post-core observers could return earlier.

The first v172 implementation repaired source through ``inspect.getsourcelines``.
That was not wrapper-safe: Python source inspection followed ``__wrapped__`` to
the historical bot_main function even though v60's ``converge`` function had
become the live deadline owner. v116/v117 then wrapped that v60 callable. The
source could therefore be found but recompiled under a different function name,
causing ``recompiled post-core convergence function missing`` in production.

This version locates the actual deadline owner in the live wrapper chain and
mutates that exact function object in place. Outer v116/v117 wrappers keep their
identity and closures. The repaired wait remains finite and strictly below the
capital freshness TTL.

v172 changes only the caller wait budget. It does not make activation succeed,
does not alter ``commit_activation()``, ``can_execute()``, capital freshness,
broker connectivity, writer/nonce authority, kill switches, risk checks, order
gates, or signal thresholds. The final gate remains fail closed exactly as
before.
"""
from __future__ import annotations

import ast
import importlib
import linecache
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

_V60_SOURCE_SUFFIX = "bot/final_production_activation_repair_v60_patch.py"
_LEGACY_SOURCE_SUFFIX = "bot/bot_main.py"
_V60_SIGNATURE = "deadline = time.monotonic() + max(1.0, min(float(timeout_s), 60.0))"
_V60_REPLACEMENT = "deadline = time.monotonic() + _nija_v172_activation_wait_s(timeout_s)"
_LEGACY_SIGNATURE = "_act_deadline = time.time() + min(timeout_s, 30.0)"
_LEGACY_REPLACEMENT = "_act_deadline = time.time() + _nija_v172_activation_wait_s(timeout_s)"


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return float(default)


def _activation_wait_seconds(requested_timeout_s: Any = 60.0) -> float:
    """Return a finite activation wait aligned with the capital pipeline.

    The result is never allowed to reach the capital freshness TTL. This is a
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


def _callable_chain(target: Any) -> list[FunctionType]:
    chain: list[FunctionType] = []
    current = target
    seen: set[int] = set()
    for _ in range(48):
        if not isinstance(current, FunctionType) or id(current) in seen:
            break
        seen.add(id(current))
        chain.append(current)
        current = getattr(current, "__wrapped__", None)
    return chain


def _normalized_filename(function: FunctionType) -> str:
    return str(function.__code__.co_filename or "").replace("\\", "/")


def _find_deadline_owner(target: FunctionType) -> tuple[FunctionType, str]:
    """Return the function object that actually owns the active wait deadline."""
    chain = _callable_chain(target)

    # v60 is the current production owner. v116/v117 are outer fail-closed
    # wrappers and must remain installed, so patch v60's object in place.
    for function in chain:
        filename = _normalized_filename(function)
        if (
            function.__code__.co_name == "converge"
            and filename.endswith(_V60_SOURCE_SUFFIX)
        ):
            return function, "v60"

    # Backward-compatible fallback for a process where v60 is not yet the
    # active owner. This keeps older startup stacks bounded without widening
    # any gate.
    for function in chain:
        filename = _normalized_filename(function)
        if (
            function.__code__.co_name == "_perform_post_core_activation_convergence"
            and filename.endswith(_LEGACY_SOURCE_SUFFIX)
        ):
            return function, "legacy_bot_main"

    details = [
        f"{fn.__code__.co_name}@{_normalized_filename(fn)}"
        for fn in chain
    ]
    raise RuntimeError(f"post-core activation deadline owner missing chain={details}")


def _exact_function_source(target: FunctionType) -> str:
    """Read this function's source without following ``__wrapped__``."""
    filename = target.__code__.co_filename
    lines = linecache.getlines(filename, target.__globals__)
    if not lines:
        raise RuntimeError(f"source unavailable for {target.__code__.co_name}:{filename}")

    full_source = "".join(lines)
    try:
        tree = ast.parse(full_source, filename=filename)
    except SyntaxError as exc:
        raise RuntimeError(f"source parse failed:{exc}") from exc

    first_line = int(target.__code__.co_firstlineno)
    candidates: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != target.__code__.co_name:
            continue
        end_line = int(getattr(node, "end_lineno", node.lineno) or node.lineno)
        decorator_lines = [int(getattr(item, "lineno", node.lineno)) for item in node.decorator_list]
        source_start = min([int(node.lineno), *decorator_lines])
        if source_start <= first_line <= end_line:
            candidates.append(node)

    if not candidates:
        raise RuntimeError(
            f"exact source node missing name={target.__code__.co_name} "
            f"first_line={first_line} file={filename}"
        )

    # Prefer the smallest containing span if similarly named nested functions
    # ever coexist in the same module.
    node = min(
        candidates,
        key=lambda item: int(getattr(item, "end_lineno", item.lineno) or item.lineno) - int(item.lineno),
    )
    end_line = int(getattr(node, "end_lineno", node.lineno) or node.lineno)
    source = "".join(lines[int(node.lineno) - 1 : end_line])
    return textwrap.dedent(source)


def _compile_repaired_function(target: FunctionType, owner_kind: str | None = None) -> FunctionType:
    """Compile a repaired copy of the exact owner without unwrapping it."""
    source = _exact_function_source(target)

    if owner_kind == "v60" or (owner_kind is None and _V60_SIGNATURE in source):
        old = _V60_SIGNATURE
        new = _V60_REPLACEMENT
    elif owner_kind == "legacy_bot_main" or (owner_kind is None and _LEGACY_SIGNATURE in source):
        old = _LEGACY_SIGNATURE
        new = _LEGACY_REPLACEMENT
    else:
        raise RuntimeError(
            "post-core activation deadline signature changed; "
            f"owner={target.__code__.co_name}"
        )

    if source.count(old) != 1:
        raise RuntimeError(
            "post-core activation deadline signature changed; "
            f"owner={target.__code__.co_name} expected exactly one {old!r}, "
            f"found {source.count(old)}"
        )

    repaired = source.replace(old, new, 1)
    namespace: dict[str, Any] = {}
    code = compile(repaired, target.__code__.co_filename, "exec")
    exec(code, target.__globals__, namespace)

    # Use the actual code symbol, not __name__. functools.wraps/manual
    # __wrapped__ chains can legitimately make those values diverge.
    replacement = namespace.get(target.__code__.co_name)
    if not isinstance(replacement, FunctionType):
        raise RuntimeError(
            "recompiled post-core convergence function missing "
            f"symbol={target.__code__.co_name} available={sorted(namespace)}"
        )
    if replacement.__code__.co_freevars != target.__code__.co_freevars:
        raise RuntimeError(
            "post-core convergence closure contract changed "
            f"before={target.__code__.co_freevars} after={replacement.__code__.co_freevars}"
        )
    return replacement


def _owner_is_patched(owner: FunctionType) -> bool:
    return bool(
        getattr(owner, _PATCH_ATTR, False)
        and "_nija_v172_activation_wait_s" in owner.__code__.co_names
    )


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

    try:
        owner, owner_kind = _find_deadline_owner(target)
    except Exception as exc:
        LOGGER.critical(
            "POST_CORE_ACTIVATION_V172_OWNER_RESOLUTION_FAILED marker=%s error=%s:%s "
            "trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    if _owner_is_patched(owner):
        setattr(target, _PATCH_ATTR, True)
        return True

    # Inject only the pure wait-budget helper into the actual owner's module
    # globals. All activation/readiness functions remain unchanged.
    owner.__globals__["_nija_v172_activation_wait_s"] = _activation_wait_seconds
    try:
        replacement = _compile_repaired_function(owner, owner_kind)
    except Exception as exc:
        LOGGER.critical(
            "POST_CORE_ACTIVATION_V172_SOURCE_REPAIR_FAILED marker=%s owner_kind=%s "
            "owner_name=%s error=%s:%s trading_fail_closed=true",
            MARKER,
            owner_kind,
            owner.__code__.co_name,
            type(exc).__name__,
            exc,
        )
        return False

    # Mutate the owner object in place. v116/v117 wrappers close over this exact
    # object, so their supervised/fail-closed behavior remains intact.
    owner.__code__ = replacement.__code__
    owner.__defaults__ = replacement.__defaults__
    owner.__kwdefaults__ = replacement.__kwdefaults__
    owner.__annotations__ = dict(getattr(replacement, "__annotations__", {}) or {})
    setattr(owner, _PATCH_ATTR, True)
    setattr(target, _PATCH_ATTR, True)

    if not _owner_is_patched(owner):
        LOGGER.critical(
            "POST_CORE_ACTIVATION_V172_POSTPATCH_VERIFY_FAILED marker=%s owner_kind=%s "
            "trading_fail_closed=true",
            MARKER,
            owner_kind,
        )
        return False

    LOGGER.critical(
        "POST_CORE_ACTIVATION_BUDGET_V172_PATCHED marker=%s owner_kind=%s owner_name=%s "
        "wrapper_depth=%d wait_s=%.1f capital_pipeline_deadline_s=%.1f freshness_ttl_s=%.1f "
        "outer_wrappers_preserved=true commit_activation_unchanged=true can_execute_unchanged=true "
        "freshness_extended=false execution_bypass=false",
        MARKER,
        owner_kind,
        owner.__code__.co_name,
        max(0, len(_callable_chain(target)) - 1),
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
            "outer_wrappers_preserved=true commit_activation_unchanged=true can_execute_unchanged=true "
            "forced_activation=false writer_nonce_risk_order_gates_unchanged=true",
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
    "_callable_chain",
    "_find_deadline_owner",
    "_exact_function_source",
    "_compile_repaired_function",
    "_patch_bot_main",
]
