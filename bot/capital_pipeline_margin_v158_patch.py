"""Bounded post-fetch publication margin for runtime capital refreshes.

Production 2026-08-19 showed v142 retiring otherwise healthy runtime capital
coordinator generations at 55 seconds while v78 deliberately permits up to 50
seconds for synchronous broker collection.  That left only ~5 seconds for the
remaining normalize, confidence, publish, event-dispatch, and downstream
readiness handoff stages.  Repeated rollovers accumulated retired daemon
coordinator workers even though the writer/core remained healthy.

v158 preserves the existing freshness and fail-closed contracts while giving the
post-fetch stages a realistic bounded margin:

* keep v78's synchronous broker fetch budget unchanged;
* keep CapitalAuthority's immutable freshness TTL unchanged;
* cap the total v142 runtime coordinator deadline strictly inside freshness;
* default the total deadline to fetch_budget + 20s (70s with the current 50s
  fetch budget), leaving at least 10s before the canonical 90s freshness TTL;
* never fabricate balances, extend publication expiry, grant execution
  authority, clear a kill switch, synthesize readiness, or dispatch orders.
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


def _bounded_deadline_seconds(v142: Any) -> float:
    """Return a total coordinator deadline strictly inside capital freshness."""
    ttl_s = max(10.0, float(v142._freshness_ttl_seconds()))
    fetch_budget_s = max(5.0, float(v142._fetch_budget_seconds()))
    ceiling = max(10.0, ttl_s - 10.0)

    try:
        requested_margin = float(
            os.environ.get("NIJA_CAPITAL_PIPELINE_PUBLISH_MARGIN_S", "20.0") or 20.0
        )
    except (TypeError, ValueError):
        requested_margin = 20.0
    margin_s = max(5.0, min(30.0, requested_margin))

    default = min(ceiling, fetch_budget_s + margin_s)
    raw = str(os.environ.get("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", "") or "").strip()
    if raw:
        try:
            requested = float(raw)
        except (TypeError, ValueError):
            requested = default
    else:
        requested = default

    # Preserve operator ability to choose a stricter deadline, but never allow
    # this liveness repair to broaden the immutable freshness window.
    return max(10.0, min(requested, ceiling))


def _patch_v142_deadline() -> bool:
    try:
        v142 = importlib.import_module("bot.capital_publication_liveness_v142_patch")
    except Exception as exc:
        LOGGER.error(
            "CAPITAL_PIPELINE_MARGIN_V158_IMPORT_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

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


def install() -> bool:
    with _LOCK:
        ready = _patch_v142_deadline()
        os.environ[_FLAG] = "1" if ready else "0"
        if ready:
            v142 = importlib.import_module("bot.capital_publication_liveness_v142_patch")
            LOGGER.critical(
                "CAPITAL_PIPELINE_MARGIN_V158 marker=%s ready=true deadline_s=%.1f fetch_budget_s=%.1f freshness_ttl_s=%.1f publication_expiry_extended=false safety_gates_bypassed=false",
                MARKER,
                _bounded_deadline_seconds(v142),
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
    "_patch_v142_deadline",
]
