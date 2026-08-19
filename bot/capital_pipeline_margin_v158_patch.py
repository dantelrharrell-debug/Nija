"""Bounded post-fetch publication margin for runtime capital refreshes.

Production 2026-08-19 showed v142 retiring otherwise healthy runtime capital
coordinator generations at the legacy 70 second deadline even after the v159
runtime-readiness layer requested more post-fetch completion headroom.  The
install order explains the regression: v159 wrapped the v142 deadline first,
then v158 wrapped that function again and re-applied the legacy
``NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S=70`` setting.

v158 is the canonical owner of the runtime capital deadline margin.  It now:

* keeps v78's synchronous broker fetch budget unchanged;
* keeps CapitalAuthority's immutable freshness TTL unchanged;
* reserves a bounded post-fetch headroom of 30 seconds by default;
* treats the old total-deadline environment value as a floor, not a value that
  may shrink below the required fetch + post-fetch completion envelope;
* caps the effective deadline strictly inside freshness (80s for the current
  90s TTL / 50s fetch budget);
* never fabricates balances, extends publication expiry, grants execution
  authority, clears a kill switch, synthesizes readiness, or dispatches orders.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.capital_pipeline_margin_v158")
MARKER = "20260819-capital-pipeline-margin-v158"
_FLAG = "NIJA_CAPITAL_PIPELINE_MARGIN_V158_READY"
_PATCH_ATTR = "_nija_capital_pipeline_margin_v158"
_LOCK = threading.RLock()


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


def _bounded_deadline_seconds(v142: Any) -> float:
    """Return the canonical total coordinator deadline inside capital freshness."""
    ttl_s = max(10.0, float(v142._freshness_ttl_seconds()))
    fetch_budget_s = max(5.0, float(v142._fetch_budget_seconds()))

    # Publication freshness remains authoritative.  Keep at least ten seconds
    # between the runtime-pipeline deadline and the immutable snapshot TTL.
    ceiling = max(10.0, ttl_s - 10.0)

    # The production 50s fetch budget needs enough room for normalize,
    # confidence, publish, event dispatch, and readiness handoff after broker
    # collection completes.  Thirty seconds gives an 80s total deadline while
    # still preserving the 10s freshness safety margin at the canonical 90s TTL.
    requested_headroom = _float_env(
        "NIJA_CAPITAL_RUNTIME_PIPELINE_POST_FETCH_HEADROOM_S",
        30.0,
    )
    headroom_s = max(5.0, min(30.0, requested_headroom))
    required = min(ceiling, fetch_budget_s + headroom_s)

    # Backward compatibility: an existing total-deadline value may request more
    # room but must no longer shrink the required post-fetch completion window.
    # This intentionally neutralizes the legacy production value of 70 seconds.
    raw = str(os.environ.get("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", "") or "").strip()
    if raw:
        try:
            configured = float(raw)
        except (TypeError, ValueError):
            configured = required
        requested = max(required, configured)
    else:
        requested = required

    return max(10.0, min(requested, ceiling))


def _patch_one_v142(v142: Any) -> bool:
    current = getattr(v142, "_runtime_pipeline_deadline_seconds", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    original = current

    @wraps(original)
    def runtime_pipeline_deadline_v158() -> float:
        return _bounded_deadline_seconds(v142)

    setattr(runtime_pipeline_deadline_v158, _PATCH_ATTR, True)
    setattr(runtime_pipeline_deadline_v158, "__wrapped__", original)
    v142._runtime_pipeline_deadline_seconds = runtime_pipeline_deadline_v158
    return True


def _patch_v142_deadline() -> bool:
    modules: list[Any] = []
    for name in (
        "bot.capital_publication_liveness_v142_patch",
        "capital_publication_liveness_v142_patch",
    ):
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        if all(module is not existing for existing in modules):
            modules.append(module)

    if not modules:
        LOGGER.error(
            "CAPITAL_PIPELINE_MARGIN_V158_IMPORT_FAILED marker=%s trading_fail_closed=true",
            MARKER,
        )
        return False

    ready = True
    for module in modules:
        ready = bool(_patch_one_v142(module)) and ready
    return ready


def _canonical_v142() -> Any:
    return importlib.import_module("bot.capital_publication_liveness_v142_patch")


def install() -> bool:
    with _LOCK:
        ready = _patch_v142_deadline()
        os.environ[_FLAG] = "1" if ready else "0"
        if ready:
            v142 = _canonical_v142()
            effective = float(v142._runtime_pipeline_deadline_seconds())
            LOGGER.critical(
                "CAPITAL_PIPELINE_MARGIN_V158 marker=%s ready=true deadline_s=%.1f fetch_budget_s=%.1f freshness_ttl_s=%.1f deadline_owner=v158 legacy_deadline_floor=true publication_expiry_extended=false safety_gates_bypassed=false",
                MARKER,
                effective,
                float(v142._fetch_budget_seconds()),
                float(v142._freshness_ttl_seconds()),
            )
        else:
            LOGGER.critical(
                "CAPITAL_PIPELINE_MARGIN_V158 marker=%s ready=false trading_fail_closed=true",
                MARKER,
            )
        return ready


__all__ = [
    "MARKER",
    "install",
    "_bounded_deadline_seconds",
    "_patch_one_v142",
    "_patch_v142_deadline",
]
