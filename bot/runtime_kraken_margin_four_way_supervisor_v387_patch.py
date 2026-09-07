"""Non-ordering Kraken margin four-way certification supervisor v387.

Canonical fast-path startup can install v367 without subsequently installing the
exact-broker scoping from v368 and the final v371 four-way protection truth.
This supervisor is deliberately observational/protective only: it waits until
v367 is genuinely ready, applies only v368's exact-broker/read-scoping wrappers,
then installs v371's SL/TP/trailing-SL/trailing-TP certification layer.

It also installs v388, the research-grounded adaptive four-way exit policy, at
startup and reasserts it after v371 so platform and registered-user exit geometry
uses the same ATR/R policy across Kraken, Coinbase, and OKX.

It intentionally does NOT call v368.install_import_hook(), because that full
installer also starts later native-backup work that may submit reduce-only
protective orders. v387 itself submits no orders, creates no exposure, fabricates
no fills/protection/readiness, changes no freshness TTLs, and grants no execution
or activation authority.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading

LOGGER = logging.getLogger("nija.runtime_kraken_margin_four_way_supervisor_v387")
MARKER = "20260907-kraken-margin-four-way-supervisor-v387"
_READY_FLAG = "NIJA_KRAKEN_MARGIN_FOUR_WAY_SUPERVISOR_V387_READY"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_STOP = threading.Event()


def _install_v388() -> bool:
    try:
        v388 = importlib.import_module("bot.runtime_research_adaptive_exit_v388_patch")
        install = getattr(v388, "install_import_hook", None) or getattr(v388, "install", None)
        return bool(callable(install) and install())
    except Exception as exc:
        LOGGER.exception(
            "RESEARCH_ADAPTIVE_EXIT_V388_INSTALL_ERROR marker=%s error=%s:%s "
            "trading_fail_closed=true safety_gates_bypassed=false",
            MARKER, type(exc).__name__, exc,
        )
        os.environ["NIJA_RESEARCH_ADAPTIVE_EXIT_V388_READY"] = "0"
        return False


def _attempt_nonordering_chain() -> tuple[bool, str]:
    if os.environ.get("NIJA_RUNTIME_KRAKEN_MARGIN_PROTECTION_TRUTH_V367_READY") != "1":
        return False, "v367_not_ready"
    try:
        v368 = importlib.import_module("bot.runtime_kraken_margin_protection_authority_v368_patch")
        v371 = importlib.import_module("bot.runtime_kraken_margin_full_protection_v371_patch")

        software = getattr(v368, "_patch_software_protection_status", None)
        coverage = getattr(v368, "_patch_margin_coverage_broker_scope", None)
        readers = getattr(v368, "_patch_account_brokers_authenticated_read_fallback", None)
        manifest = getattr(v368, "_register_manifest", None)
        if not all(callable(fn) for fn in (software, coverage, readers, manifest)):
            return False, "v368_scoping_surface_unavailable"

        scoped = bool(software() and coverage() and readers() and manifest())
        if not scoped:
            os.environ[getattr(v368, "_READY_FLAG", "NIJA_RUNTIME_KRAKEN_MARGIN_PROTECTION_AUTHORITY_V368_READY")] = "0"
            return False, "v368_scoping_not_ready"

        install_v371 = getattr(v371, "install_import_hook", None) or getattr(v371, "install", None)
        if not callable(install_v371):
            return False, "v371_installer_unavailable"
        full = bool(install_v371())
        ready = bool(
            full
            and os.environ.get("NIJA_RUNTIME_KRAKEN_MARGIN_FULL_PROTECTION_V371_READY") == "1"
        )
        os.environ[getattr(v368, "_READY_FLAG", "NIJA_RUNTIME_KRAKEN_MARGIN_PROTECTION_AUTHORITY_V368_READY")] = "1" if ready else "0"
        if not ready:
            return False, "v371_not_ready"

        adaptive_ready = _install_v388()
        if not adaptive_ready:
            return False, "v388_not_ready_after_v371"

        LOGGER.critical(
            "KRAKEN_MARGIN_FOUR_WAY_SUPERVISOR_V387_READY marker=%s "
            "v367_ready=true v368_exact_broker_scope=true v371_four_way_ready=true "
            "v388_research_adaptive_exit_ready=true "
            "full_v368_installer_called=false native_backup_started=false orders_submitted=false "
            "execution_authority_unchanged=true activation_unchanged=true freshness_unchanged=true "
            "risk_gates_unchanged=true protection_fabricated=false safety_gates_bypassed=false",
            MARKER,
        )
        return True, "ready"
    except Exception as exc:
        return False, f"{type(exc).__name__}:{exc}"


def _worker() -> None:
    attempt = 0
    last_reason = "not_started"
    while not _STOP.wait(1.0):
        attempt += 1
        ready, reason = _attempt_nonordering_chain()
        last_reason = reason
        if ready:
            os.environ[_READY_FLAG] = "1"
            return
        if attempt == 1 or attempt % 10 == 0:
            LOGGER.warning(
                "KRAKEN_MARGIN_FOUR_WAY_SUPERVISOR_V387_WAIT marker=%s attempt=%d reason=%s "
                "trading_fail_closed=true orders_submitted=false safety_gates_bypassed=false",
                MARKER,
                attempt,
                reason,
            )
    LOGGER.info(
        "KRAKEN_MARGIN_FOUR_WAY_SUPERVISOR_V387_STOP marker=%s last_reason=%s",
        MARKER,
        last_reason,
    )


def install_import_hook() -> bool:
    global _THREAD
    # v388 is global (not Kraken-specific), so install it immediately. This
    # also forces its fail-closed fallback environment before any later worker
    # can inherit the old tight fixed trailing percentages.
    adaptive_started = _install_v388()
    if not adaptive_started:
        LOGGER.error(
            "KRAKEN_MARGIN_FOUR_WAY_SUPERVISOR_V387_ADAPTIVE_POLICY_UNREADY marker=%s "
            "v388_ready=false trading_fail_closed=true",
            MARKER,
        )
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return adaptive_started
        _STOP.clear()
        os.environ.setdefault(_READY_FLAG, "0")
        _THREAD = threading.Thread(
            target=_worker,
            name="KrakenMarginFourWaySupervisorV387",
            daemon=True,
        )
        _THREAD.start()
        started = bool(_THREAD.is_alive())
    LOGGER.critical(
        "KRAKEN_MARGIN_FOUR_WAY_SUPERVISOR_V387_STARTED marker=%s started=%s "
        "v388_adaptive_started=%s waits_for_v367=true nonordering_chain=true "
        "native_backup_started=false orders_submitted=false trading_fail_closed_until_v371=true "
        "safety_gates_bypassed=false",
        MARKER,
        str(started).lower(),
        str(adaptive_started).lower(),
    )
    return bool(started and adaptive_started)


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook"]
