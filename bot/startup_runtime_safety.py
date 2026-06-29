"""Startup-time safety normalisation for live runtime flags."""

from __future__ import annotations

from collections.abc import MutableMapping
import logging
import os
import sys
import threading
import time

TRUTHY_ENV_VALUES = {"1", "true", "yes", "on", "enabled"}
LIVE_BYPASS_FLAGS = (
    "NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK",
    "NIJA_DISABLE_WRITER_LOCK",
    "NIJA_FORCE_ACTIVATION",
    "NIJA_SKIP_STARTUP_PHASE_GATE",
)

logger = logging.getLogger("nija.startup_runtime_safety")
_POSITION_SYNC_AUTOWIRE_STARTED = False
# Lock protecting the module-level _POSITION_SYNC_AUTOWIRE_STARTED flag so
# concurrent callers (e.g. multiple threads calling normalize_runtime_startup_env
# at startup) cannot race past the guard and launch duplicate worker threads.
_POSITION_SYNC_AUTOWIRE_LOCK = threading.Lock()


def env_truthy(value: str | None) -> bool:
    """Return ``True`` when *value* represents an enabled environment flag."""

    return str(value or "").strip().lower() in TRUTHY_ENV_VALUES


def live_mode_enabled(env: MutableMapping[str, str]) -> bool:
    """Return ``True`` when the runtime should be treated as live mode."""

    return not env_truthy(env.get("DRY_RUN_MODE")) and not env_truthy(env.get("PAPER_MODE"))


def _invoke_position_sync(strategy, source: str) -> None:
    """Invoke startup position sync on *strategy* exactly once.

    Guard: ``_startup_position_sync_done`` is set on the strategy instance
    before the sync runs so that re-entrant or duplicate calls (e.g. from
    reconnect handlers, health monitors, or multiple startup hooks) are
    silently ignored.
    """
    if getattr(strategy, "_startup_position_sync_done", False):
        return
    # Set the flag BEFORE calling sync so that any re-entrant call triggered
    # during sync (e.g. from a broker reconnect callback) is also a no-op.
    setattr(strategy, "_startup_position_sync_done", True)
    try:
        try:
            from bot.startup_position_sync import sync_exchange_positions_on_startup
        except ImportError:
            from startup_position_sync import sync_exchange_positions_on_startup  # type: ignore[import]
        logger.warning("EXCHANGE_POSITION_SYNC invocation starting source=%s", source)
        adopted = sync_exchange_positions_on_startup(strategy)
        logger.warning("EXCHANGE_POSITION_SYNC invocation complete adopted=%s source=%s", adopted, source)
    except Exception as exc:
        logger.exception("EXCHANGE_POSITION_SYNC invocation failed source=%s error=%s", source, exc)


def _patch_trading_strategy_class(cls) -> bool:
    """Wrap *cls.__init__* to trigger position sync after construction.

    Guard: ``_nija_position_sync_wrapped`` is set on the wrapper function so
    that calling this function multiple times on the same class is idempotent —
    the class ``__init__`` is patched at most once regardless of how many times
    this function is called.

    The original ``__init__`` is captured in a closure variable
    (``original_init``) *before* the wrapper is defined, so the wrapper always
    calls the true original — never the already-patched version — preventing
    double-wrapping and infinite recursion.
    """
    # Save the original __init__ BEFORE defining the wrapper so the closure
    # always refers to the unpatched version.
    original_init = getattr(cls, "__init__", None)
    if original_init is None:
        return False
    # Idempotency guard: if this class has already been patched, return True
    # without re-wrapping (which would cause double-wrapping / infinite recursion).
    if getattr(original_init, "_nija_position_sync_wrapped", False):
        return True

    def _init_with_position_sync(self, *args, **kwargs):
        # Call the ORIGINAL __init__, not the patched one.
        original_init(self, *args, **kwargs)
        _invoke_position_sync(self, "TradingStrategy.__init__")

    _init_with_position_sync._nija_position_sync_wrapped = True  # type: ignore[attr-defined]
    cls.__init__ = _init_with_position_sync
    logger.warning("EXCHANGE_POSITION_SYNC TradingStrategy.__init__ patched from startup_runtime_safety")
    return True


def _install_position_sync_autowire() -> None:
    """Start the background autowire worker thread — at most once per process.

    Thread-safe: protected by ``_POSITION_SYNC_AUTOWIRE_LOCK`` so concurrent
    callers cannot race past the ``_POSITION_SYNC_AUTOWIRE_STARTED`` flag and
    launch duplicate worker threads.
    """
    global _POSITION_SYNC_AUTOWIRE_STARTED
    # Fast path: check without the lock first (common case after first call).
    if _POSITION_SYNC_AUTOWIRE_STARTED:
        return
    with _POSITION_SYNC_AUTOWIRE_LOCK:
        # Re-check inside the lock to handle the race between the fast-path
        # check and lock acquisition.
        if _POSITION_SYNC_AUTOWIRE_STARTED:
            return
        _POSITION_SYNC_AUTOWIRE_STARTED = True

    if not env_truthy(os.getenv("NIJA_STARTUP_POSITION_SYNC_ENABLED", "true")):
        logger.warning("EXCHANGE_POSITION_SYNC autowire disabled by NIJA_STARTUP_POSITION_SYNC_ENABLED=false")
        return

    def _worker() -> None:
        deadline = time.monotonic() + float(os.getenv("NIJA_POSITION_SYNC_AUTOWIRE_TIMEOUT_S", "120") or "120")
        logger.warning("EXCHANGE_POSITION_SYNC autowire worker started source=startup_runtime_safety")
        while time.monotonic() < deadline:
            for module_name in ("bot.trading_strategy", "trading_strategy"):
                module = sys.modules.get(module_name)
                cls = getattr(module, "TradingStrategy", None) if module is not None else None
                if cls is not None and _patch_trading_strategy_class(cls):
                    return
            time.sleep(0.25)
        logger.warning("EXCHANGE_POSITION_SYNC autowire timeout: TradingStrategy class was not observed")

    threading.Thread(target=_worker, name="startup-position-sync-autowire", daemon=True).start()


def normalize_runtime_startup_env(env: MutableMapping[str, str]) -> list[str]:
    """Fail closed on test/unsafe live-mode flags and restore default HF scalp mode."""

    _install_position_sync_autowire()

    notes: list[str] = []
    if not live_mode_enabled(env):
        return notes

    bypass_confirmed = env_truthy(env.get("NIJA_CONFIRM_BYPASS_RISKS"))

    if not bypass_confirmed:
        for flag in LIVE_BYPASS_FLAGS:
            if env_truthy(env.get(flag)):
                env[flag] = "0" if "LOCK" in flag else "false"
                notes.append(f"cleared:{flag}")

    hf_flip_mode = env_truthy(env.get("HF_FLIP_MODE"))
    hf_scalp_mode = env_truthy(env.get("HF_SCALP_MODE"))
    if not hf_flip_mode and not hf_scalp_mode:
        env["HF_SCALP_MODE"] = "1"
        notes.append("enabled:HF_SCALP_MODE")

    env.setdefault("HF_SCALPING_MODE", env.get("HF_SCALP_MODE", "1"))

    # Ensure generation mismatch recovery is enabled by default so the bot
    # can self-heal from diverged generation counters (e.g. local=882339 vs
    # redis=753) without operator intervention.  Operators can explicitly
    # disable this by setting NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED=false.
    if not env_truthy(env.get("NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED")):
        env["NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED"] = "true"
        notes.append("enabled:NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED")

    return notes
