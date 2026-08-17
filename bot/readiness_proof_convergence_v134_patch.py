"""Converge activation/readiness consumers on one current capital proof.

v134 repairs two contradictory readiness paths exposed by production v133:

* ``CapitalAuthority`` declares a 90-second canonical freshness TTL, but its
  no-argument ``is_stale()`` method still defaulted to 60 seconds.  Consumers
  using ``is_fresh()``/snapshot publication therefore disagreed with v16/v60
  consumers using ``is_stale()``.
* the activation monitor and v60 observational gate could treat historical
  readiness latches/cached balances as current capital proof after the current
  snapshot had become stale.

Safety contract:
- retain v133's fail-closed readiness revocation and LIVE_ACTIVE -> OFF path;
- never fabricate capital, broker registration, or snapshot freshness;
- never clear kill switch or SEAK and never grant writer/nonce authority;
- never force LIVE_ACTIVE;
- keep the existing short-lived v34 handoff only through v16's TTL-validated
  proof collector; sticky env/latch state is not accepted independently.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Any

LOGGER = logging.getLogger("nija.readiness_proof_convergence_v134")
MARKER = "20260817-readiness-proof-convergence-v134"
RELEASE_ID = "20260817-runtime-convergence-v134"
_FLAG = "NIJA_READINESS_PROOF_CONVERGENCE_V134_INSTALLED"
_LOCK = threading.RLock()
_INSTALLED = False


def _import_first(*names: str) -> Any:
    last: BaseException | None = None
    for name in names:
        try:
            return importlib.import_module(name)
        except Exception as exc:  # pragma: no cover - diagnostic fallback
            last = exc
    if last is not None:
        raise last
    raise ImportError("no module names supplied")


def _canonical_ttl_s() -> float:
    """Return the CapitalAuthority lifecycle TTL used by publication/is_fresh."""
    ca = _import_first("bot.capital_authority", "capital_authority")
    try:
        ttl = float(getattr(ca, "_DEFAULT_FRESHNESS_TTL_S", 90.0) or 90.0)
    except (TypeError, ValueError, OverflowError):
        ttl = 90.0
    return max(1.0, ttl)


def _patch_capital_authority_staleness_default() -> bool:
    """Make no-argument is_stale() use the authority's canonical TTL.

    Explicit TTL callers retain their exact requested threshold.  This changes
    only the inconsistent legacy default and makes ``is_stale()`` agree with
    ``is_fresh()`` and snapshot-publication expiry.
    """
    ca = _import_first("bot.capital_authority", "capital_authority")
    cls = getattr(ca, "CapitalAuthority", None)
    current = getattr(cls, "is_stale", None) if cls is not None else None
    if not callable(current):
        return False
    if getattr(current, "_nija_v134_canonical_ttl", False):
        return True

    original = current
    canonical_ttl = _canonical_ttl_s()

    def is_stale_v134(self: Any, ttl_s: float | None = None) -> bool:
        effective = canonical_ttl if ttl_s is None else float(ttl_s)
        return bool(original(self, ttl_s=effective))

    is_stale_v134._nija_v134_canonical_ttl = True  # type: ignore[attr-defined]
    is_stale_v134.__wrapped__ = original  # type: ignore[attr-defined]
    cls.is_stale = is_stale_v134
    LOGGER.critical(
        "CAPITAL_STALENESS_DEFAULT_V134_CONVERGED marker=%s canonical_ttl_s=%.1f "
        "explicit_ttl_preserved=true",
        MARKER,
        canonical_ttl,
    )
    return True


def _current_capital_proof() -> dict[str, Any]:
    """Read v16's current capital proof, including only its TTL-validated handoff."""
    v16 = _import_first(
        "preactivation_readiness_convergence_v16_patch",
        "bot.preactivation_readiness_convergence_v16_patch",
    )
    reader = getattr(v16, "_capital_snapshot", None)
    if not callable(reader):
        raise RuntimeError("v16_capital_snapshot_unavailable")
    proof = reader()
    if not isinstance(proof, dict):
        raise RuntimeError("v16_capital_snapshot_invalid")
    return dict(proof)


def _proof_fields(proof: dict[str, Any]) -> tuple[bool, bool, float, int]:
    hydrated = bool(proof.get("hydrated", False))
    stale = bool(proof.get("stale", True))
    try:
        real = float(proof.get("real", 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError):
        real = 0.0
    try:
        registered = int(float(proof.get("registered", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        registered = 0
    return hydrated, stale, real, registered


def _current_capital_accepted(proof: dict[str, Any]) -> bool:
    hydrated, stale, real, registered = _proof_fields(proof)
    return bool(hydrated and not stale and real > 0.0 and registered > 0)


def _patch_activation_monitor() -> bool:
    """Reject sticky historical snapshot latches and un-aged broker caches."""
    monitor = _import_first(
        "bot.activation_pending_commit_monitor_patch",
        "activation_pending_commit_monitor_patch",
    )
    current = getattr(monitor, "_capital_ready_snapshot", None)
    if callable(current) and getattr(current, "_nija_v134_current_proof", False):
        return True
    if not callable(current):
        return False
    original = current

    def capital_ready_snapshot_v134() -> tuple[bool, dict[str, Any]]:
        try:
            proof = _current_capital_proof()
            hydrated, stale, real, registered = _proof_fields(proof)
            accepted = _current_capital_accepted(proof)
            source = str(proof.get("source", "v16_current_capital") or "v16_current_capital")
            reason = "ok" if accepted else "current_snapshot_not_accepted"
            meta = {
                "hydrated": hydrated,
                "real_capital": real,
                "stale": stale,
                "registered_brokers": registered,
                # Compatibility field only.  It now reflects current proof and
                # is never read from CapitalAuthority's historical first latch.
                "accepted_latch": accepted,
                "reason": reason,
                "source": source,
                "current_proof": True,
            }
            LOGGER.info(
                "ACTIVATION_CAPITAL_PROOF_V134 marker=%s accepted=%s hydrated=%s "
                "stale=%s real=%.2f registered=%d source=%s sticky_latch_used=false "
                "unaged_cache_used=false",
                MARKER,
                accepted,
                hydrated,
                stale,
                real,
                registered,
                source,
            )
            return accepted, meta
        except Exception as exc:
            LOGGER.critical(
                "ACTIVATION_CAPITAL_PROOF_V134_FAILED marker=%s err=%s:%s "
                "accepted=false trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False, {
                "hydrated": False,
                "real_capital": 0.0,
                "stale": True,
                "registered_brokers": 0,
                "accepted_latch": False,
                "reason": f"current_proof_error:{type(exc).__name__}:{exc}",
                "source": "v134_fail_closed",
                "current_proof": True,
            }

    capital_ready_snapshot_v134._nija_v134_current_proof = True  # type: ignore[attr-defined]
    capital_ready_snapshot_v134.__wrapped__ = original  # type: ignore[attr-defined]
    monitor._capital_ready_snapshot = capital_ready_snapshot_v134
    LOGGER.critical(
        "ACTIVATION_MONITOR_V134_CONVERGED marker=%s current_v16_proof=true "
        "sticky_first_snapshot_latch=false unaged_broker_cache_fallback=false",
        MARKER,
    )
    return True


def _install_v60_observer() -> bool:
    """Install the v60 observational gate from the same current proof source."""
    v60 = _import_first(
        "bot.final_production_activation_repair_v60_patch",
        "final_production_activation_repair_v60_patch",
    )
    tsm = _import_first("bot.trading_state_machine", "trading_state_machine")
    current_gate = getattr(tsm, "_capital_readiness_gate", None)
    if not callable(current_gate):
        return False
    original_gate = getattr(current_gate, "__wrapped__", current_gate)

    def observational_gate_v134() -> tuple[bool, str]:
        try:
            proof = _current_capital_proof()
            hydrated, stale, real, registered = _proof_fields(proof)
            source = str(proof.get("source", "v16_current_capital") or "v16_current_capital")
        except Exception as exc:
            return False, f"CA_READY=false: current_proof_error:{type(exc).__name__}:{exc}"
        LOGGER.info(
            "CAPITAL_READINESS_OBSERVATIONAL_V134 marker=%s hydrated=%s stale=%s "
            "real=%.2f registered=%d source=%s private_io=false sticky_handoff=false",
            MARKER,
            hydrated,
            stale,
            real,
            registered,
            source,
        )
        if not hydrated:
            return False, "CA_READY=false: capital_authority_not_hydrated"
        if stale:
            return False, "CA_READY=false: capital_authority_stale"
        if real <= 0.0:
            return False, "CA_READY=false: real_capital_nonpositive"
        if registered <= 0:
            return False, "CA_READY=false: no_registered_capital_broker"
        return True, "ok"

    observational_gate_v134._nija_v60_observational = True  # type: ignore[attr-defined]
    observational_gate_v134._nija_v134_current_proof = True  # type: ignore[attr-defined]
    observational_gate_v134.__wrapped__ = original_gate  # type: ignore[attr-defined]

    def patch_capital_readiness_observer_v134() -> bool:
        tsm._capital_readiness_gate = observational_gate_v134
        return True

    patch_capital_readiness_observer_v134._nija_v134_owner = True  # type: ignore[attr-defined]
    v60._patch_capital_readiness_observer = patch_capital_readiness_observer_v134
    tsm._capital_readiness_gate = observational_gate_v134
    LOGGER.critical(
        "FINAL_ACTIVATION_V60_CAPITAL_GATE_V134_CONVERGED marker=%s "
        "current_v16_proof=true sticky_handoff=false private_io=false",
        MARKER,
    )
    return True


def _patch_release_manifest() -> bool:
    manifest = _import_first("bot.runtime_release_manifest_patch", "runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["readiness_proof_convergence_v134"] = _FLAG
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED and os.environ.get(_FLAG) == "1":
            # Reassert the two function owners because older convergence layers
            # can replay their installers during long-running processes.
            try:
                return bool(_patch_activation_monitor() and _install_v60_observer())
            except Exception:
                return False
        try:
            ok = bool(
                _patch_capital_authority_staleness_default()
                and _patch_activation_monitor()
                and _install_v60_observer()
                and _patch_release_manifest()
            )
        except Exception as exc:
            LOGGER.critical(
                "READINESS_PROOF_CONVERGENCE_V134_INSTALL_FAILED marker=%s err=%s:%s "
                "trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            ok = False
        if not ok:
            os.environ.pop(_FLAG, None)
            return False
        os.environ[_FLAG] = "1"
        _INSTALLED = True
        LOGGER.critical(
            "READINESS_PROOF_CONVERGENCE_V134_INSTALLED marker=%s release=%s "
            "canonical_stale_ttl=true current_proof_single_source=true "
            "sticky_latch_acceptance=false unaged_cache_acceptance=false "
            "kill_switch_unchanged=true seak_unchanged=true nonce_gates_unchanged=true "
            "risk_gates_unchanged=true force_live=false",
            MARKER,
            RELEASE_ID,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_canonical_ttl_s",
    "_current_capital_proof",
    "_current_capital_accepted",
    "_patch_capital_authority_staleness_default",
    "_patch_activation_monitor",
    "_install_v60_observer",
]
