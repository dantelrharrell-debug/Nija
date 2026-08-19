"""Fail-closed final verification for a maturing Redis nonce writer lease.

This patch preserves the configured nonce-lease stability requirement. It only
converts a transient same-owner/same-token maturity race into one final bounded
verification. Token/owner changes, stability regression, missing status, writer
authority loss, or Redis errors remain hard failures.
"""
from __future__ import annotations

import importlib
import logging
import os
import time
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.nonce_lease_maturity_v155")
_MARKER = "20260819-nonce-lease-maturity-v155"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _status_identity(status: dict[str, Any]) -> tuple[str, str]:
    token = str(status.get("token") or "").strip()
    owner = str(status.get("owner_instance") or status.get("owner_id") or "").strip()
    return token, owner


def _final_wait_cap_s() -> float:
    configured = _safe_float(os.environ.get("NIJA_NONCE_LEASE_FINAL_VERIFY_MAX_WAIT_S", "2.0"), 2.0)
    return min(5.0, max(0.25, configured))


def _final_same_lease_maturity_check(tsm: ModuleType, prior_error: str) -> tuple[bool, str]:
    """Perform one bounded proof re-check without weakening the stability threshold."""
    if "nonce lease unstable" not in str(prior_error or "").lower():
        return False, prior_error

    platform_key = (
        os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
        or os.environ.get("KRAKEN_API_KEY", "").strip()
    )
    if not platform_key:
        return False, prior_error

    try:
        try:
            from bot.distributed_nonce_manager import get_distributed_nonce_manager, make_api_key_id
            from bot.execution_authority_context import assert_startup_write_authority
        except ImportError:
            from distributed_nonce_manager import get_distributed_nonce_manager, make_api_key_id  # type: ignore[import]
            from execution_authority_context import assert_startup_write_authority  # type: ignore[import]

        required_fn = getattr(tsm, "_nonce_lease_stability_requirement_s", lambda: 0.0)
        required_s = max(0.0, _safe_float(required_fn(), 0.0))
        if required_s <= 0.0:
            return True, ""

        assert_startup_write_authority()
        manager = get_distributed_nonce_manager()
        key_id = make_api_key_id(platform_key)
        status_fn = getattr(manager, "get_writer_lease_status", None)
        if not callable(status_fn):
            return False, f"{prior_error}; final_verify=status_unavailable"

        before = status_fn(key_id)
        if not isinstance(before, dict) or before.get("enabled") is False:
            return False, f"{prior_error}; final_verify=invalid_status_before"

        token_before, owner_before = _status_identity(before)
        stable_before = _safe_float(before.get("stable_for_s"), -1.0)
        if not token_before or not owner_before or stable_before < 0.0:
            return False, f"{prior_error}; final_verify=incomplete_identity_before"

        if stable_before >= required_s:
            logger.warning(
                "NONCE_LEASE_FINAL_MATURITY_VERIFIED marker=%s stable_for=%.3f required=%.3f token=%s owner=%s waited=0.000",
                _MARKER,
                stable_before,
                required_s,
                token_before,
                owner_before,
            )
            return True, ""

        remaining_s = max(0.0, required_s - stable_before)
        wait_cap_s = _final_wait_cap_s()
        if remaining_s > wait_cap_s:
            return False, (
                f"{prior_error}; final_verify=remaining_exceeds_cap "
                f"remaining={remaining_s:.3f}s cap={wait_cap_s:.3f}s"
            )

        wait_s = min(wait_cap_s, remaining_s + 0.15)
        logger.warning(
            "NONCE_LEASE_FINAL_MATURITY_WAIT marker=%s stable_for=%.3f required=%.3f remaining=%.3f token=%s owner=%s wait=%.3f",
            _MARKER,
            stable_before,
            required_s,
            remaining_s,
            token_before,
            owner_before,
            wait_s,
        )
        time.sleep(wait_s)

        assert_startup_write_authority()
        after = status_fn(key_id)
        if not isinstance(after, dict) or after.get("enabled") is False:
            return False, f"{prior_error}; final_verify=invalid_status_after"

        token_after, owner_after = _status_identity(after)
        stable_after = _safe_float(after.get("stable_for_s"), -1.0)
        if token_after != token_before or owner_after != owner_before:
            return False, (
                f"{prior_error}; final_verify=lease_identity_changed "
                f"token_before={token_before} token_after={token_after} "
                f"owner_before={owner_before} owner_after={owner_after}"
            )
        if stable_after + 1e-6 < stable_before:
            return False, (
                f"{prior_error}; final_verify=stability_regressed "
                f"before={stable_before:.3f} after={stable_after:.3f}"
            )
        if stable_after < required_s:
            return False, (
                f"{prior_error}; final_verify=still_immature "
                f"stable_for={stable_after:.3f}s required={required_s:.3f}s"
            )

        logger.warning(
            "NONCE_LEASE_FINAL_MATURITY_VERIFIED marker=%s stable_for=%.3f required=%.3f token=%s owner=%s waited=%.3f",
            _MARKER,
            stable_after,
            required_s,
            token_after,
            owner_after,
            wait_s,
        )
        return True, ""
    except Exception as exc:
        return False, f"{prior_error}; final_verify_error={type(exc).__name__}:{exc}"


def _patch_module(tsm: ModuleType) -> bool:
    if getattr(tsm, "_NIJA_NONCE_LEASE_MATURITY_V155_PATCHED", False):
        return True

    try:
        base_patch = importlib.import_module("bot.live_entry_completion_repair_patch")
        patch_fn = getattr(base_patch, "_patch_trading_state_machine", None)
        if callable(patch_fn):
            patch_fn(tsm)
    except Exception as exc:
        logger.error(
            "NONCE_LEASE_MATURITY_V155_BASE_INSTALL_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            _MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    original = getattr(tsm, "_nonce_writer_lease_gate", None)
    if not callable(original):
        logger.error(
            "NONCE_LEASE_MATURITY_V155_GATE_MISSING marker=%s trading_fail_closed=true",
            _MARKER,
        )
        return False
    if getattr(original, "_nija_nonce_lease_maturity_v155", False):
        setattr(tsm, "_NIJA_NONCE_LEASE_MATURITY_V155_PATCHED", True)
        return True

    def guarded_gate() -> tuple[bool, str]:
        ok, err = original()
        if ok:
            return True, ""
        return _final_same_lease_maturity_check(tsm, str(err or ""))

    guarded_gate._nija_nonce_lease_maturity_v155 = True  # type: ignore[attr-defined]
    guarded_gate.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(tsm, "_nonce_writer_lease_gate", guarded_gate)
    setattr(tsm, "_NIJA_NONCE_LEASE_MATURITY_V155_PATCHED", True)
    os.environ["NIJA_NONCE_LEASE_MATURITY_V155_INSTALLED"] = "1"
    logger.critical(
        "NONCE_LEASE_MATURITY_V155_INSTALLED marker=%s full_stability_requirement_preserved=true circuit_breaker_bypass=false",
        _MARKER,
    )
    return True


def install() -> bool:
    try:
        tsm = importlib.import_module("bot.trading_state_machine")
    except Exception as exc:
        logger.error(
            "NONCE_LEASE_MATURITY_V155_IMPORT_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            _MARKER,
            type(exc).__name__,
            exc,
        )
        return False
    return _patch_module(tsm)


__all__ = ["install", "_patch_module", "_final_same_lease_maturity_check"]
