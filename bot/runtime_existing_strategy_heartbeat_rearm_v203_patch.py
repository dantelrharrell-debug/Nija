"""Re-arm heartbeat verification when an existing strategy is republished (v203).

Production startup can create a ``TradingStrategy`` before the final canonical
broker set is hydrated. ``strategy_publication_patch`` later reuses that same
object and repairs its brokers/symbols instead of calling ``TradingStrategy``
``__init__`` again. The constructor is the normal owner of heartbeat scheduling,
so a reused instance can reach RUNNING_SUPERVISED with every structural gate
ready while no heartbeat verifier thread exists to create the required genuine
execution proof.

v127's direct Step 2.5 publisher captures ``strategy_publication_patch._publish``
in a closure when v127 installs. If v203 wraps ``_publish`` later, that cached
closure can still call the pre-v203 publication function and bypass the re-arm.
v203 therefore guards both publication surfaces: the canonical ``_publish``
primitive and bot_main's Step 2.5 runtime publication helper.

A second production ordering case installs v203 after the canonical strategy has
already been published. In that case there may be no later publication call for
the wrappers to observe, so v203 also discovers that already-published strategy
and idempotently re-arms its existing scheduler during install. It never creates
or replaces a strategy object.

A third production case can replace the canonical ``strategy_publication_patch``
module object during import-identity convergence after v127 has cached the old
``_publish`` callable.  The live strategy then remains reachable only through
v127's cached publisher closure while the current module reports
``_PUBLISHED=None``.  v203 recovers that exact already-created object from the
cached callable's globals and re-arms only its existing heartbeat scheduler.

This patch repairs scheduling liveness only:
* it runs only when the existing HEARTBEAT_TRADE policy is enabled,
* it never writes heartbeat/execution proof itself,
* it never marks readiness or grants execution authority,
* it calls the existing ``_schedule_heartbeat_trade`` implementation,
* that implementation still traverses writer/nonce/risk/kill-switch,
  reconciliation, capital, min-notional, order and fill gates,
* duplicate live heartbeat threads remain blocked by the strategy's own lock.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_existing_strategy_heartbeat_rearm_v203")
MARKER = "20260823-existing-strategy-heartbeat-rearm-v203"
_READY_FLAG = "NIJA_EXISTING_STRATEGY_HEARTBEAT_REARM_V203_READY"
_PATCH_ATTR = "_nija_existing_strategy_heartbeat_rearm_v203"
_BOT_MAIN_PATCH_ATTR = "_nija_existing_strategy_heartbeat_rearm_v203_bot_main"
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUTHY


def _thread_alive(strategy: Any) -> bool:
    thread = getattr(strategy, "_heartbeat_trade_thread", None)
    return bool(
        thread is not None
        and callable(getattr(thread, "is_alive", None))
        and thread.is_alive()
    )


def _ensure_heartbeat_scheduler(strategy: Any) -> bool:
    """Ensure the existing live strategy owns an active heartbeat verifier."""
    if strategy is None:
        return False

    if not _truthy("HEARTBEAT_TRADE"):
        LOGGER.info(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_SKIPPED marker=%s reason=policy_disabled",
            MARKER,
        )
        return True

    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        LOGGER.info(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_SKIPPED marker=%s reason=simulation_mode",
            MARKER,
        )
        return True

    if bool(getattr(strategy, "_heartbeat_trade_success", False)) and bool(
        getattr(strategy, "_heartbeat_trade_completed", False)
    ):
        LOGGER.info(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_SKIPPED marker=%s reason=already_verified",
            MARKER,
        )
        return True

    if _thread_alive(strategy):
        LOGGER.info(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_SKIPPED marker=%s reason=thread_alive",
            MARKER,
        )
        return True

    scheduler = getattr(strategy, "_schedule_heartbeat_trade", None)
    if not callable(scheduler):
        LOGGER.critical(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_FAILED marker=%s reason=scheduler_missing "
            "execution_authority_granted=false proof_fabricated=false trading_fail_closed=true",
            MARKER,
        )
        return False

    # Early-created/legacy strategy objects may have cached the policy before
    # v200/v201 aligned the live runtime environment. Refresh only that cached
    # scheduler flag; no readiness or authority state is touched here.
    setattr(strategy, "_heartbeat_trade_enabled", True)
    if getattr(strategy, "_heartbeat_trade_lock", None) is None:
        setattr(strategy, "_heartbeat_trade_lock", threading.Lock())
    if not hasattr(strategy, "_heartbeat_trade_thread"):
        setattr(strategy, "_heartbeat_trade_thread", None)
    if not hasattr(strategy, "_heartbeat_trade_completed"):
        setattr(strategy, "_heartbeat_trade_completed", False)
    if not hasattr(strategy, "_heartbeat_trade_success"):
        setattr(strategy, "_heartbeat_trade_success", False)

    try:
        scheduler()
    except Exception as exc:
        LOGGER.critical(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_FAILED marker=%s reason=scheduler_exception "
            "error=%s:%s execution_authority_granted=false proof_fabricated=false trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    alive = _thread_alive(strategy)
    LOGGER.critical(
        "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_TRIGGERED marker=%s thread_alive=%s "
        "policy_refreshed=true existing_scheduler_only=true execution_authority_granted=false "
        "proof_fabricated=false writer_nonce_risk_killswitch_reconciliation_capital_order_fill_gates_unchanged=true "
        "forced_activation=false safety_gates_bypassed=false",
        MARKER,
        str(alive).lower(),
    )
    return alive


def _strategy_from_cached_runtime_publisher() -> Any:
    """Recover v127's already-published strategy from its cached ``_publish``.

    v127 closes over a ``publish`` callable.  If import-identity convergence later
    replaces ``bot.strategy_publication_patch`` in ``sys.modules``, that callable
    still points at the detached module globals containing the real ``_PUBLISHED``
    object.  Reading that pointer is safe: this function never constructs,
    republishes, replaces, or mutates strategy/readiness state.
    """
    try:
        bot_main = importlib.import_module("bot.bot_main")
    except Exception as exc:
        LOGGER.warning(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_CACHED_LOOKUP_DEFERRED marker=%s "
            "reason=bot_main_import_failed error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return None

    roots = [
        getattr(bot_main, "_publish_canonical_strategy_for_runtime", None),
        getattr(bot_main, "_nija_v203_previous_runtime_publisher", None),
    ]
    seen: set[int] = set()

    for root in roots:
        current = root
        while callable(current) and id(current) not in seen:
            seen.add(id(current))
            code = getattr(current, "__code__", None)
            closure = getattr(current, "__closure__", None) or ()
            freevars = tuple(getattr(code, "co_freevars", ()) or ())
            for name, cell in zip(freevars, closure):
                if name != "publish":
                    continue
                try:
                    cached_publish = cell.cell_contents
                except ValueError:
                    continue
                if not callable(cached_publish):
                    continue
                globals_dict = getattr(cached_publish, "__globals__", None)
                if not isinstance(globals_dict, dict):
                    continue
                strategy = globals_dict.get("_PUBLISHED")
                if strategy is None or not callable(getattr(strategy, "run_cycle", None)):
                    continue
                LOGGER.critical(
                    "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_CACHED_PUBLISHER_RECOVERED marker=%s "
                    "same_existing_object=true detached_publication_globals=true strategy_replaced=false "
                    "execution_authority_granted=false proof_fabricated=false safety_gates_bypassed=false",
                    MARKER,
                )
                return strategy
            current = getattr(current, "__wrapped__", None)

    return None


def _already_published_strategy(module: Any) -> Any:
    """Return an existing published strategy without constructing a replacement."""
    strategy = getattr(module, "_PUBLISHED", None)
    if strategy is not None:
        return strategy

    finder = getattr(module, "_existing", None)
    class_getter = getattr(module, "_strategy_class", None)
    if callable(finder):
        strategy_class = None
        if callable(class_getter):
            try:
                strategy_class = class_getter()
            except Exception as exc:
                LOGGER.warning(
                    "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_EXISTING_LOOKUP_DEFERRED marker=%s "
                    "reason=strategy_class_lookup_failed error=%s:%s",
                    MARKER,
                    type(exc).__name__,
                    exc,
                )
            else:
                try:
                    strategy = finder(strategy_class)
                except Exception as exc:
                    LOGGER.warning(
                        "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_EXISTING_LOOKUP_DEFERRED marker=%s "
                        "reason=existing_strategy_lookup_failed error=%s:%s",
                        MARKER,
                        type(exc).__name__,
                        exc,
                    )
                if strategy is not None:
                    return strategy

    return _strategy_from_cached_runtime_publisher()


def _rearm_already_published_strategy(module: Any) -> bool:
    """Close the install-after-publication gap without fabricating execution proof."""
    strategy = _already_published_strategy(module)
    if strategy is None:
        LOGGER.info(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_IMMEDIATE_SKIPPED marker=%s "
            "reason=no_existing_strategy future_publication_guarded=true cached_v127_checked=true",
            MARKER,
        )
        return True

    ready = _ensure_heartbeat_scheduler(strategy)
    if not ready:
        LOGGER.critical(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_IMMEDIATE_FAILED marker=%s "
            "reason=existing_scheduler_not_alive execution_authority_granted=false "
            "proof_fabricated=false trading_fail_closed=true",
            MARKER,
        )
        return False

    LOGGER.critical(
        "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_IMMEDIATE_READY marker=%s "
        "existing_strategy_found=true existing_scheduler_only=true strategy_replaced=false "
        "execution_authority_granted=false proof_fabricated=false forced_activation=false "
        "safety_gates_bypassed=false",
        MARKER,
    )
    return True


def _wrap_publication_primitive(module: Any) -> bool:
    current = getattr(module, "_publish", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    previous = current

    @wraps(previous)
    def _publish_with_heartbeat_rearm(strategy: Any) -> Any:
        result = previous(strategy)
        _ensure_heartbeat_scheduler(strategy)
        return result

    setattr(_publish_with_heartbeat_rearm, _PATCH_ATTR, True)
    setattr(module, "_nija_v203_previous_publish", previous)
    setattr(module, "_publish", _publish_with_heartbeat_rearm)
    installed = getattr(module, "_publish", None)
    return bool(callable(installed) and getattr(installed, _PATCH_ATTR, False))


def _wrap_bot_main_runtime_publisher() -> bool:
    """Catch v127's cached publication closure at the Step 2.5 boundary."""
    try:
        bot_main = importlib.import_module("bot.bot_main")
    except Exception as exc:
        LOGGER.critical(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_BOT_MAIN_WRAP_FAILED marker=%s "
            "reason=bot_main_import_failed error=%s:%s trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    current = getattr(bot_main, "_publish_canonical_strategy_for_runtime", None)
    if not callable(current):
        LOGGER.critical(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_BOT_MAIN_WRAP_FAILED marker=%s "
            "reason=runtime_publisher_missing trading_fail_closed=true",
            MARKER,
        )
        return False
    if getattr(current, _BOT_MAIN_PATCH_ATTR, False):
        return True

    previous = current

    @wraps(previous)
    def _publish_runtime_with_heartbeat_rearm(explicit_broker: Any) -> Any:
        strategy = previous(explicit_broker)
        if strategy is not None:
            _ensure_heartbeat_scheduler(strategy)
        return strategy

    # wraps() intentionally preserves v127's helper marker from the inner
    # function so later v127 reassertions recognize the direct publisher as
    # still installed instead of replacing this outer liveness wrapper.
    setattr(_publish_runtime_with_heartbeat_rearm, _BOT_MAIN_PATCH_ATTR, True)
    setattr(bot_main, "_nija_v203_previous_runtime_publisher", previous)
    setattr(bot_main, "_publish_canonical_strategy_for_runtime", _publish_runtime_with_heartbeat_rearm)
    installed = getattr(bot_main, "_publish_canonical_strategy_for_runtime", None)
    return bool(callable(installed) and getattr(installed, _BOT_MAIN_PATCH_ATTR, False))


def install() -> bool:
    """Guard publication paths and re-arm any strategy published before install."""
    with _LOCK:
        try:
            module = importlib.import_module("bot.strategy_publication_patch")
        except Exception as exc:
            os.environ[_READY_FLAG] = "0"
            LOGGER.critical(
                "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_INSTALL_FAILED marker=%s reason=publication_import_failed "
                "error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False

        primitive_ready = _wrap_publication_primitive(module)
        bot_main_ready = _wrap_bot_main_runtime_publisher()
        immediate_ready = _rearm_already_published_strategy(module)
        ready = bool(primitive_ready and bot_main_ready and immediate_ready)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_INSTALL_FAILED marker=%s "
                "primitive_ready=%s bot_main_ready=%s immediate_ready=%s trading_fail_closed=true",
                MARKER,
                str(primitive_ready).lower(),
                str(bot_main_ready).lower(),
                str(immediate_ready).lower(),
            )
            return False

        LOGGER.critical(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_READY marker=%s ready=true "
            "publication_primitive_guarded=true bot_main_step2_5_guarded=true "
            "install_after_publication_gap_closed=true v127_cached_publish_bypass_closed=true "
            "detached_v127_cached_publication_recovery=true existing_strategy_only=true "
            "existing_scheduler_only=true execution_authority_granted=false proof_fabricated=false "
            "forced_activation=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_ensure_heartbeat_scheduler",
    "_strategy_from_cached_runtime_publisher",
    "_already_published_strategy",
    "_rearm_already_published_strategy",
]
