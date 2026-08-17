"""Converge snapshot bridging and activation on one current publication proof.

Production v135 exposed a remaining activation livelock: the legacy activation
snapshot bridge could convert a stale CapitalAuthority observation back to
freshness from historical readiness/handoff flags, then attempt a secondary
LIVE transition after the canonical coordinator had rejected readiness.

v136 makes the bridge observational only:

* bridge acceptance requires the current v134 capital proof AND a non-expired
  CapitalAuthority publication;
* historical first-snapshot/readiness latches never turn stale capital fresh;
* cycle-capital augmentation remains available for a genuinely current snapshot;
* TradingStateMachine.commit_activation() remains the only activation commit
  authority; the bridge never calls _force_live_active_transition();
* kill-switch, writer, nonce, risk, execution, and freshness gates are unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from datetime import datetime, timezone
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.activation_publication_convergence_v136")
MARKER = "20260817-activation-publication-convergence-v136"
RELEASE_ID = "20260817-runtime-convergence-v136"
_FLAG = "NIJA_ACTIVATION_PUBLICATION_CONVERGENCE_V136_INSTALLED"
_LOCK = threading.RLock()
_INSTALLED = False
_LAST_BLOCK_SIGNATURE = ""


def _import_first(*names: str) -> Any:
    last: BaseException | None = None
    for name in names:
        try:
            return importlib.import_module(name)
        except Exception as exc:
            last = exc
    if last is not None:
        raise last
    raise ImportError("no module names supplied")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except (TypeError, ValueError, OverflowError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(value if value not in (None, "") else default))
    except (TypeError, ValueError, OverflowError):
        return default


def _publication_current(authority: Any) -> tuple[bool, dict[str, Any]]:
    """Return whether CapitalAuthority's latest publication is current.

    Runtime expiry is checked here even when v135's reader wrapper is not yet
    installed, so import ordering cannot temporarily resurrect an expired
    publication.  Missing/invalid publication state fails closed.
    """
    getter = getattr(authority, "get_snapshot_publication_status", None)
    if not callable(getter):
        return False, {"reason": "publication_status_unavailable", "stale": True}
    try:
        status = getter()
    except Exception as exc:
        return False, {
            "reason": f"publication_status_error:{type(exc).__name__}:{exc}",
            "stale": True,
        }
    if status is None:
        return False, {"reason": "publication_status_missing", "stale": True}

    stale = bool(getattr(status, "stale", True))
    accepted = bool(getattr(status, "accepted", False))
    reason = str(getattr(status, "reason", "") or "")
    expiry = getattr(status, "expiry", None)
    if isinstance(expiry, datetime):
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        else:
            expiry = expiry.astimezone(timezone.utc)
        if datetime.now(timezone.utc) >= expiry:
            stale = True
            reason = "expired_after_publish"

    return (not stale), {
        "accepted": accepted,
        "stale": stale,
        "reason": reason or ("ok" if not stale else "publication_stale"),
        "timestamp": getattr(status, "timestamp", None),
        "expiry": expiry,
    }


def _current_capital_meta() -> tuple[bool, dict[str, Any]]:
    """Build bridge metadata exclusively from current canonical proof.

    v134 owns capital-proof semantics.  v136 adds the immutable publication
    expiry as a second, fail-closed condition so a fresh-looking handoff/latch
    cannot outrun the authoritative publication lifetime.
    """
    try:
        v134 = _import_first(
            "bot.readiness_proof_convergence_v134_patch",
            "readiness_proof_convergence_v134_patch",
        )
        proof_reader = getattr(v134, "_current_capital_proof", None)
        proof_acceptor = getattr(v134, "_current_capital_accepted", None)
        if not callable(proof_reader) or not callable(proof_acceptor):
            raise RuntimeError("v134_current_capital_proof_unavailable")
        proof = proof_reader()
        if not isinstance(proof, dict):
            raise RuntimeError("v134_current_capital_proof_invalid")

        proof_accepted = bool(proof_acceptor(proof))
        hydrated = bool(proof.get("hydrated", False))
        proof_stale = bool(proof.get("stale", True))
        real = max(0.0, _number(proof.get("real", 0.0)))
        registered = max(0, _integer(proof.get("registered", 0)))
        source = str(proof.get("source", "v134_current_capital") or "v134_current_capital")

        ca_module = _import_first("bot.capital_authority", "capital_authority")
        authority = ca_module.get_capital_authority()
        publication_ok, publication = _publication_current(authority)

        brokers_ready = False
        try:
            bridge = _import_first(
                "bot.activation_snapshot_bridge_patch",
                "activation_snapshot_bridge_patch",
            )
            checker = getattr(bridge, "_mabm_brokers_ready", None)
            if callable(checker):
                brokers_ready = bool(checker())
        except Exception:
            brokers_ready = False

        accepted = bool(proof_accepted and publication_ok)
        stale = bool(proof_stale or not publication_ok)
        meta = {
            "ca_available": True,
            # Compatibility telemetry only: this mirrors CURRENT acceptance and
            # is never sourced from CapitalAuthority.first_snap_accepted.
            "accepted_latch": accepted,
            "hydrated": hydrated,
            "stale": stale,
            "real_capital": real,
            "valid_brokers": registered,
            "brokers_ready": brokers_ready,
            "conditions_met": accepted,
            "current_proof": True,
            "proof_accepted": proof_accepted,
            "publication_current": publication_ok,
            "publication": publication,
            "source": source,
        }
        return accepted, meta
    except Exception as exc:
        return False, {
            "ca_available": False,
            "accepted_latch": False,
            "hydrated": False,
            "stale": True,
            "real_capital": 0.0,
            "valid_brokers": 0,
            "brokers_ready": False,
            "conditions_met": False,
            "current_proof": True,
            "proof_accepted": False,
            "publication_current": False,
            "reason": f"current_publication_proof_error:{type(exc).__name__}:{exc}",
            "source": "v136_fail_closed",
        }


def _log_block(meta: dict[str, Any]) -> None:
    global _LAST_BLOCK_SIGNATURE
    signature = ":".join(
        (
            str(bool(meta.get("proof_accepted", False))).lower(),
            str(bool(meta.get("publication_current", False))).lower(),
            str(bool(meta.get("stale", True))).lower(),
            str(meta.get("source", "unknown")),
        )
    )
    with _LOCK:
        if signature == _LAST_BLOCK_SIGNATURE:
            return
        _LAST_BLOCK_SIGNATURE = signature
    LOGGER.critical(
        "ACTIVATION_PUBLICATION_V136_BLOCK marker=%s proof_accepted=%s "
        "publication_current=%s stale=%s source=%s canonical_commit_only=true "
        "force_fallback=false trading_fail_closed=true",
        MARKER,
        bool(meta.get("proof_accepted", False)),
        bool(meta.get("publication_current", False)),
        bool(meta.get("stale", True)),
        meta.get("source", "unknown"),
    )


def _unwrap_legacy_bridge_commit(current: Any) -> Any:
    """Remove only the legacy activation-snapshot bridge wrapper.

    Other wrappers below it remain intact.  v136 itself carries the bridge
    ownership marker so the legacy bridge autowire worker will not re-wrap it.
    """
    candidate = current
    if (
        callable(candidate)
        and getattr(candidate, "_nija_activation_snapshot_bridge_wrapped", False)
        and not getattr(candidate, "_nija_activation_publication_v136", False)
    ):
        wrapped = getattr(candidate, "__wrapped__", None)
        if callable(wrapped):
            candidate = wrapped
    return candidate


def _patch_trading_state_machine_class(cls: type) -> bool:
    current = getattr(cls, "commit_activation", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_activation_publication_v136", False):
        return True

    canonical_commit = _unwrap_legacy_bridge_commit(current)
    if not callable(canonical_commit):
        return False

    @wraps(canonical_commit)
    def commit_activation_v136(self: Any, cycle_capital: Any = None) -> bool:
        accepted, meta = _current_capital_meta()
        bridged_capital = cycle_capital
        if accepted:
            try:
                bridge = _import_first(
                    "bot.activation_snapshot_bridge_patch",
                    "activation_snapshot_bridge_patch",
                )
                sync_first = getattr(bridge, "_sync_first_snapshot_flag", None)
                augment = getattr(bridge, "_augment_cycle_capital", None)
                if callable(sync_first):
                    sync_first(self, meta)
                if callable(augment):
                    bridged_capital = augment(cycle_capital, meta)
            except Exception as exc:
                LOGGER.warning(
                    "ACTIVATION_PUBLICATION_V136_AUGMENT_FAILED marker=%s err=%s:%s "
                    "canonical_snapshot_unchanged=true trading_fail_closed=true",
                    MARKER,
                    type(exc).__name__,
                    exc,
                )
                bridged_capital = cycle_capital
        else:
            _log_block(meta)

        # Exactly one activation authority.  Do not perform any fallback or
        # state mutation after this result; canonical commit_activation owns it.
        return bool(canonical_commit(self, cycle_capital=bridged_capital))

    setattr(commit_activation_v136, "_nija_activation_publication_v136", True)
    # Deliberately retain the legacy bridge marker so its autowire worker treats
    # this stricter owner as already patched instead of wrapping it again.
    setattr(commit_activation_v136, "_nija_activation_snapshot_bridge_wrapped", True)
    setattr(commit_activation_v136, "_nija_v136_original", canonical_commit)
    cls.commit_activation = commit_activation_v136
    LOGGER.critical(
        "ACTIVATION_PUBLICATION_V136_TSM_CONVERGED marker=%s class=%s "
        "canonical_commit_only=true secondary_force_transition_removed=true",
        MARKER,
        cls.__name__,
    )
    return True


def _patch_bridge_owner() -> bool:
    bridge = _import_first(
        "bot.activation_snapshot_bridge_patch",
        "activation_snapshot_bridge_patch",
    )
    tsm = _import_first("bot.trading_state_machine", "trading_state_machine")
    cls = getattr(tsm, "TradingStateMachine", None)
    if not isinstance(cls, type):
        return False

    # Direct-scan bridge calls this module global dynamically, so replacing the
    # reader also converges that path without removing useful scan augmentation.
    bridge._capital_snapshot_meta = _current_capital_meta
    bridge._patch_trading_state_machine_class = _patch_trading_state_machine_class
    return _patch_trading_state_machine_class(cls)


def _patch_release_manifest() -> bool:
    try:
        manifest = _import_first(
            "bot.runtime_release_manifest_patch",
            "runtime_release_manifest_patch",
        )
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["activation_publication_convergence_v136"] = _FLAG
        manifest.RELEASE_ID = RELEASE_ID
        return True
    except Exception:
        return False


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        try:
            bridge_ok = _patch_bridge_owner()
            manifest_ok = _patch_release_manifest()
            ok = bool(bridge_ok and manifest_ok)
        except Exception as exc:
            LOGGER.critical(
                "ACTIVATION_PUBLICATION_V136_INSTALL_FAILED marker=%s err=%s:%s "
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
            "ACTIVATION_PUBLICATION_CONVERGENCE_V136_INSTALLED marker=%s release=%s "
            "current_v134_proof_required=true publication_expiry_required=true "
            "historical_latch_freshness=false canonical_commit_only=true "
            "kill_switch_unchanged=true nonce_unchanged=true risk_gates_unchanged=true "
            "execution_authority_unchanged=true force_live=false",
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
    "_publication_current",
    "_current_capital_meta",
    "_unwrap_legacy_bridge_commit",
    "_patch_trading_state_machine_class",
    "_patch_bridge_owner",
]
